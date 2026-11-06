#!/usr/bin/env python3
"""
Conversor de imagens com interface gráfica (Tkinter + Pillow)

Requisitos:  pip install "pillow>=11.3" pymupdf
Executar:    python conversor_imagens.py

Entrada : PNG, JPG/JPEG, WebP, AVIF, BMP e SVG
Saída   : JPG, PNG, WebP, AVIF e BMP

Recursos:
- Você escolhe quais formatos de entrada aceitar e para qual formato converter
- Adicionar arquivos avulsos ou uma pasta inteira (com ou sem subpastas)
- Qualidade ajustável (JPG, WebP e AVIF) e opção WebP sem perdas
- Preserva perfil de cor ICC, EXIF e DPI quando o formato de saída permite
- Transparência preservada em PNG, WebP e AVIF; em JPG e BMP é composta
  sobre a cor de fundo escolhida
- SVG (vetorial) é rasterizado na largura em pixels que você definir
- Conversão em segundo plano, com barra de progresso e log
- Opção de sobrescrever, renomear ou ignorar arquivos já existentes
"""

import os
import queue
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk, colorchooser

try:
    from PIL import Image
except ImportError:
    raise SystemExit('Pillow não está instalado. Rode:  pip install "pillow>=11.3"')


# --------------------------------------------------------------------------
# Suporte opcional: AVIF (Pillow 11.3+) e SVG (PyMuPDF)
# --------------------------------------------------------------------------
def _suporta_avif():
    try:
        from PIL import features
        if features.check("avif"):
            return True
    except Exception:
        pass
    try:
        import pillow_avif  # noqa: F401  (plugin alternativo para Pillow antigo)
        return True
    except Exception:
        return False


try:
    import pymupdf
    if not hasattr(pymupdf, "open"):
        raise ImportError
except ImportError:
    try:
        import fitz as pymupdf
        if not hasattr(pymupdf, "open"):
            pymupdf = None
    except ImportError:
        pymupdf = None

TEM_AVIF = _suporta_avif()
TEM_SVG = pymupdf is not None


# --------------------------------------------------------------------------
# Formatos
# --------------------------------------------------------------------------
FORMATOS = {
    "PNG":  {"rotulo": "PNG",       "exts": (".png",),           "ext_saida": ".png"},
    "JPEG": {"rotulo": "JPG/JPEG",  "exts": (".jpg", ".jpeg"),   "ext_saida": ".jpg"},
    "WEBP": {"rotulo": "WebP",      "exts": (".webp",),          "ext_saida": ".webp"},
    "AVIF": {"rotulo": "AVIF",      "exts": (".avif",),          "ext_saida": ".avif"},
    "BMP":  {"rotulo": "BMP",       "exts": (".bmp",),           "ext_saida": ".bmp"},
    "SVG":  {"rotulo": "SVG",       "exts": (".svg",),           "ext_saida": None},
}
ENTRADA = ["PNG", "JPEG", "WEBP", "AVIF", "BMP", "SVG"]
ROTULO_SAIDA = {"JPG": "JPEG", "PNG": "PNG", "WebP": "WEBP", "AVIF": "AVIF", "BMP": "BMP"}

DISPONIVEL = {chave: True for chave in FORMATOS}
DISPONIVEL["AVIF"] = TEM_AVIF
DISPONIVEL["SVG"] = TEM_SVG

SAIDAS_DISPONIVEIS = [r for r, k in ROTULO_SAIDA.items() if DISPONIVEL[k]]

DICAS = {
    "JPEG": "JPG sempre comprime com perdas. Com qualidade 100 e cores 4:4:4 (usado aqui) "
            "a diferença é invisível a olho nu. Transparência é trocada pela cor de fundo.",
    "PNG":  "PNG é sem perdas e mantém a transparência, mas os arquivos podem ficar grandes.",
    "WEBP": "WebP mantém a transparência. Use qualidade ajustável ou marque 'Sem perdas' "
            "para preservar cada pixel.",
    "AVIF": "AVIF comprime muito bem e mantém a transparência, porém a conversão é mais lenta.",
    "BMP":  "BMP não tem compressão: os arquivos ficam grandes. Transparência é trocada "
            "pela cor de fundo.",
}
DICA_COMUM = ("  Imagens de origem JPG, WebP ou AVIF já têm perdas e perdem um pouco mais "
              "ao serem recomprimidas. Animações: só o primeiro quadro é convertido. "
              "Arquivos que já estão no formato de saída são ignorados.")


def formato_do_arquivo(caminho):
    """Devolve a chave do formato ('PNG', 'JPEG'...) pela extensão, ou None."""
    ext = os.path.splitext(caminho)[1].lower()
    for chave, f in FORMATOS.items():
        if ext in f["exts"]:
            return chave
    return None


# --------------------------------------------------------------------------
# Lógica de conversão
# --------------------------------------------------------------------------
def rasterizar_svg(caminho, largura):
    """Desenha o SVG em pixels na largura pedida (altura proporcional)."""
    doc = pymupdf.open(caminho)
    try:
        pagina = doc[0]
        if pagina.rect.width <= 0:
            raise ValueError("SVG sem dimensões válidas")
        zoom = largura / pagina.rect.width
        pix = pagina.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom), alpha=True)
        return Image.frombytes("RGBA", (pix.width, pix.height), pix.samples)
    finally:
        doc.close()


def _tem_alfa(img):
    bandas = img.getbands()
    return (
        "A" in bandas or "a" in bandas
        or (img.mode in ("P", "L", "RGB") and "transparency" in img.info)
    )


def _achatar(img, fundo):
    """Compõe a imagem com transparência sobre uma cor sólida."""
    rgba = img.convert("RGBA")
    base = Image.new("RGBA", rgba.size, tuple(fundo) + (255,))
    return Image.alpha_composite(base, rgba).convert("RGB")


def preparar(img, fmt, fundo):
    """Ajusta o modo de cor da imagem ao que o formato de saída aceita."""
    if img.mode.startswith("I;16") or img.mode == "I":
        if fmt == "PNG" and img.mode.startswith("I;16"):
            return img  # PNG guarda 16 bits sem problema
        img = img.point(lambda p: p * (1 / 256)).convert("L")

    alfa = _tem_alfa(img)
    if fmt in ("JPEG", "BMP"):
        if alfa:
            return _achatar(img, fundo)
        return img if img.mode in ("RGB", "L") else img.convert("RGB")
    if fmt == "PNG":
        if alfa:
            return img if img.mode in ("RGBA", "LA") else img.convert("RGBA")
        return img if img.mode in ("RGB", "L") else img.convert("RGB")
    # WEBP e AVIF
    return img.convert("RGBA" if alfa else "RGB")


def salvar(img, destino, fmt, op, meta):
    """Grava a imagem no formato pedido com as opções escolhidas."""
    q = int(op["qualidade"])
    opcoes = {"format": fmt}

    if fmt == "JPEG":
        opcoes.update(quality=q, optimize=op["otimizar"])
        if img.mode == "RGB":
            opcoes["subsampling"] = 0  # 4:4:4 = sem perda de resolução de cor
    elif fmt == "PNG":
        opcoes["optimize"] = op["otimizar"]
    elif fmt == "WEBP":
        if op["sem_perdas"]:
            opcoes.update(lossless=True, quality=100)
        else:
            opcoes["quality"] = q
        opcoes["method"] = 6 if op["otimizar"] else 4
    elif fmt == "AVIF":
        opcoes.update(quality=q, subsampling="4:4:4")

    if op["metadados"]:
        if meta.get("icc") and fmt != "BMP":
            opcoes["icc_profile"] = meta["icc"]
        if meta.get("dpi") and fmt in ("JPEG", "PNG", "BMP"):
            opcoes["dpi"] = meta["dpi"]
        if meta.get("exif") and fmt != "BMP":
            opcoes["exif"] = meta["exif"]

    try:
        img.save(destino, **opcoes)
    except Exception:
        # Metadados corrompidos podem impedir o salvamento: tenta sem eles
        if "exif" in opcoes or "icc_profile" in opcoes:
            opcoes.pop("exif", None)
            opcoes.pop("icc_profile", None)
            img.save(destino, **opcoes)
        else:
            raise


def converter_imagem(origem, destino, fmt, op):
    """
    Converte `origem` para o formato `fmt` ('JPEG', 'PNG', 'WEBP', 'AVIF', 'BMP').
    op: dict com qualidade, fundo, metadados, otimizar, sem_perdas, largura_svg.
    """
    if formato_do_arquivo(origem) == "SVG":
        if not TEM_SVG:
            raise RuntimeError("Suporte a SVG indisponível. Rode: pip install pymupdf")
        img = rasterizar_svg(origem, op["largura_svg"])
        salvar(preparar(img, fmt, op["fundo"]), destino, fmt, op, {})
        return

    with Image.open(origem) as im:
        im.load()
        meta = {
            "icc": im.info.get("icc_profile"),
            "dpi": im.info.get("dpi"),
            "exif": im.info.get("exif"),
        }
        if im.mode == "CMYK":
            meta["icc"] = None  # perfil CMYK não serve para a imagem já em RGB
        salvar(preparar(im, fmt, op["fundo"]), destino, fmt, op, meta)


def caminho_livre(caminho):
    """Gera 'nome (1).ext', 'nome (2).ext'... se o arquivo já existir."""
    if not os.path.exists(caminho):
        return caminho
    base, ext = os.path.splitext(caminho)
    n = 1
    while os.path.exists(f"{base} ({n}){ext}"):
        n += 1
    return f"{base} ({n}){ext}"


# --------------------------------------------------------------------------
# Interface
# --------------------------------------------------------------------------
class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Conversor de imagens")
        self.geometry("820x800")
        self.minsize(740, 680)

        self.arquivos = []
        self.fila = queue.Queue()
        self.convertendo = False
        self.cancelar = False
        self.cor_fundo = (255, 255, 255)

        self.var_entrada = {k: tk.BooleanVar(value=DISPONIVEL[k]) for k in ENTRADA}
        self.var_fmt_saida = tk.StringVar(value=SAIDAS_DISPONIVEIS[0])
        self.var_pasta_saida = tk.StringVar()
        self.var_mesma_pasta = tk.BooleanVar(value=True)
        self.var_qualidade = tk.IntVar(value=100)
        self.var_sem_perdas = tk.BooleanVar(value=False)
        self.var_metadados = tk.BooleanVar(value=True)
        self.var_otimizar = tk.BooleanVar(value=True)
        self.var_existente = tk.StringVar(value="renomear")
        self.var_svg = tk.StringVar(value="1024")

        self._montar_ui()
        self.after(100, self._processar_fila)

    # ---------------------------- construção da UI ----------------------
    def _montar_ui(self):
        estilo = ttk.Style(self)
        try:
            estilo.theme_use("clam")
        except tk.TclError:
            pass

        raiz = ttk.Frame(self, padding=12)
        raiz.pack(fill="both", expand=True)

        # --- Formatos de entrada e saída
        quadro_fmt = ttk.LabelFrame(raiz, text="Formatos", padding=8)
        quadro_fmt.pack(fill="x")

        ttk.Label(quadro_fmt, text="Entrada (aceitos ao adicionar):").grid(
            row=0, column=0, sticky="w")
        caixas = ttk.Frame(quadro_fmt)
        caixas.grid(row=0, column=1, sticky="w", padx=8)
        for k in ENTRADA:
            ttk.Checkbutton(
                caixas, text=FORMATOS[k]["rotulo"], variable=self.var_entrada[k],
                state="normal" if DISPONIVEL[k] else "disabled",
            ).pack(side="left", padx=(0, 10))

        ttk.Label(quadro_fmt, text="Saída (converter para):").grid(
            row=1, column=0, sticky="w", pady=(6, 0))
        self.cmb_saida = ttk.Combobox(
            quadro_fmt, textvariable=self.var_fmt_saida, values=SAIDAS_DISPONIVEIS,
            state="readonly", width=10)
        self.cmb_saida.grid(row=1, column=1, sticky="w", padx=8, pady=(6, 0))
        self.cmb_saida.bind("<<ComboboxSelected>>", lambda _e: self._atualizar_opcoes())

        faltando = []
        if not TEM_AVIF:
            faltando.append('AVIF (instale "pillow>=11.3")')
        if not TEM_SVG:
            faltando.append("SVG (instale pymupdf)")
        if faltando:
            ttk.Label(quadro_fmt, foreground="#a33", wraplength=740, justify="left",
                      text="Indisponível neste computador: " + "; ".join(faltando)
                      ).grid(row=2, column=0, columnspan=2, sticky="w", pady=(6, 0))

        # --- Lista de arquivos
        quadro_lista = ttk.LabelFrame(raiz, text="Imagens", padding=8)
        quadro_lista.pack(fill="both", expand=True, pady=(10, 0))

        botoes = ttk.Frame(quadro_lista)
        botoes.pack(fill="x", pady=(0, 6))
        ttk.Button(botoes, text="Adicionar arquivos...",
                   command=self.adicionar_arquivos).pack(side="left")
        ttk.Button(botoes, text="Adicionar pasta...",
                   command=self.adicionar_pasta).pack(side="left", padx=6)
        ttk.Button(botoes, text="Remover selecionados",
                   command=self.remover_selecionados).pack(side="left")
        ttk.Button(botoes, text="Limpar lista",
                   command=self.limpar_lista).pack(side="left", padx=6)

        corpo = ttk.Frame(quadro_lista)
        corpo.pack(fill="both", expand=True)
        self.lista = tk.Listbox(corpo, selectmode="extended", height=7,
                                activestyle="none")
        barra = ttk.Scrollbar(corpo, orient="vertical", command=self.lista.yview)
        self.lista.configure(yscrollcommand=barra.set)
        self.lista.pack(side="left", fill="both", expand=True)
        barra.pack(side="right", fill="y")

        self.lbl_contagem = ttk.Label(quadro_lista, text="0 arquivo(s)")
        self.lbl_contagem.pack(anchor="w", pady=(6, 0))

        # --- Opções
        op = ttk.LabelFrame(raiz, text="Opções", padding=8)
        op.pack(fill="x", pady=10)
        op.columnconfigure(1, weight=1)

        ttk.Checkbutton(
            op, text="Salvar na mesma pasta de cada original",
            variable=self.var_mesma_pasta, command=self._atualizar_pasta,
        ).grid(row=0, column=0, columnspan=3, sticky="w")

        ttk.Label(op, text="Pasta de saída:").grid(row=1, column=0, sticky="w", pady=4)
        self.ent_saida = ttk.Entry(op, textvariable=self.var_pasta_saida)
        self.ent_saida.grid(row=1, column=1, sticky="ew", padx=6)
        self.btn_saida = ttk.Button(op, text="Escolher...", command=self.escolher_saida)
        self.btn_saida.grid(row=1, column=2)

        ttk.Label(op, text="Qualidade:").grid(row=2, column=0, sticky="w", pady=4)
        self.escala = ttk.Scale(op, from_=1, to=100, orient="horizontal",
                                command=self._ao_mudar_qualidade)
        self.escala.set(100)
        self.escala.grid(row=2, column=1, sticky="ew", padx=6)
        self.lbl_q = ttk.Label(op, text="100", width=5)
        self.lbl_q.grid(row=2, column=2, sticky="w")

        self.chk_sem_perdas = ttk.Checkbutton(
            op, text="WebP sem perdas (preserva cada pixel; ignora a qualidade)",
            variable=self.var_sem_perdas, command=self._atualizar_opcoes)
        self.chk_sem_perdas.grid(row=3, column=0, columnspan=3, sticky="w")

        ttk.Label(op, text="Fundo (transparência):").grid(row=4, column=0, sticky="w", pady=4)
        self.amostra = tk.Label(op, bg="#ffffff", width=6, relief="sunken")
        self.amostra.grid(row=4, column=1, sticky="w", padx=6)
        self.btn_cor = ttk.Button(op, text="Escolher cor...", command=self.escolher_cor)
        self.btn_cor.grid(row=4, column=2)

        ttk.Label(op, text="Largura do SVG (px):").grid(row=5, column=0, sticky="w", pady=4)
        quadro_svg = ttk.Frame(op)
        quadro_svg.grid(row=5, column=1, sticky="w", padx=6)
        self.spn_svg = ttk.Spinbox(quadro_svg, from_=16, to=16384, increment=64,
                                   textvariable=self.var_svg, width=8)
        self.spn_svg.pack(side="left")
        ttk.Label(quadro_svg, foreground="#555555",
                  text="  SVG é vetorial e vira pixels nessa largura").pack(side="left")
        if not TEM_SVG:
            self.spn_svg.state(["disabled"])

        ttk.Label(op, text="Se o arquivo já existir:").grid(row=6, column=0, sticky="w", pady=4)
        quadro_ex = ttk.Frame(op)
        quadro_ex.grid(row=6, column=1, columnspan=2, sticky="w", padx=6)
        for texto, valor in (("Renomear", "renomear"), ("Sobrescrever", "sobrescrever"),
                             ("Ignorar", "ignorar")):
            ttk.Radiobutton(quadro_ex, text=texto, value=valor,
                            variable=self.var_existente).pack(side="left", padx=(0, 12))

        ttk.Checkbutton(
            op, text="Preservar metadados (perfil de cor ICC, EXIF, DPI) quando o formato permitir",
            variable=self.var_metadados,
        ).grid(row=7, column=0, columnspan=3, sticky="w")
        ttk.Checkbutton(
            op, text="Otimizar compressão (arquivo menor, mesma qualidade; pode demorar mais)",
            variable=self.var_otimizar,
        ).grid(row=8, column=0, columnspan=3, sticky="w")

        self.lbl_dica = ttk.Label(op, foreground="#555555", wraplength=740, justify="left")
        self.lbl_dica.grid(row=9, column=0, columnspan=3, sticky="w", pady=(8, 0))

        # --- Ações e progresso
        rodape = ttk.Frame(raiz)
        rodape.pack(fill="x")
        self.btn_converter = ttk.Button(rodape, text="Converter", command=self.iniciar)
        self.btn_converter.pack(side="left")
        self.btn_cancelar = ttk.Button(rodape, text="Cancelar", command=self.cancelar_conversao,
                                       state="disabled")
        self.btn_cancelar.pack(side="left", padx=6)
        self.progresso = ttk.Progressbar(rodape, mode="determinate")
        self.progresso.pack(side="left", fill="x", expand=True, padx=10)
        self.lbl_prog = ttk.Label(rodape, text="0/0", width=8)
        self.lbl_prog.pack(side="left")

        self.log = tk.Text(raiz, height=6, state="disabled", wrap="word")
        self.log.pack(fill="both", pady=(10, 0))

        self._atualizar_pasta()
        self._atualizar_opcoes()

    # ---------------------------- formatos ------------------------------
    def _fmt_saida(self):
        return ROTULO_SAIDA[self.var_fmt_saida.get()]

    def _aceita(self, caminho):
        k = formato_do_arquivo(caminho)
        return bool(k and DISPONIVEL[k] and self.var_entrada[k].get())

    def _formatos_ativos(self):
        return [k for k in ENTRADA if DISPONIVEL[k] and self.var_entrada[k].get()]

    @staticmethod
    def _estado(widget, ativo):
        widget.state(["!disabled"] if ativo else ["disabled"])

    def _atualizar_opcoes(self):
        fmt = self._fmt_saida()
        sem_perdas = fmt == "WEBP" and self.var_sem_perdas.get()
        self._estado(self.escala, fmt in ("JPEG", "WEBP", "AVIF") and not sem_perdas)
        self._estado(self.chk_sem_perdas, fmt == "WEBP")
        self._estado(self.btn_cor, fmt in ("JPEG", "BMP"))
        self.lbl_dica.config(text=DICAS[fmt] + DICA_COMUM)

    # ---------------------------- ações da lista ------------------------
    def adicionar_arquivos(self):
        ativos = self._formatos_ativos()
        if not ativos:
            messagebox.showwarning("Atenção", "Marque ao menos um formato de entrada.")
            return
        padroes = " ".join("*" + e for k in ativos for e in FORMATOS[k]["exts"])
        caminhos = filedialog.askopenfilenames(
            title="Selecione imagens",
            filetypes=[("Formatos de entrada marcados", padroes),
                       ("Todos os arquivos", "*.*")],
        )
        self._adicionar(caminhos)

    def adicionar_pasta(self):
        if not self._formatos_ativos():
            messagebox.showwarning("Atenção", "Marque ao menos um formato de entrada.")
            return
        pasta = filedialog.askdirectory(title="Selecione uma pasta com imagens")
        if not pasta:
            return
        incluir_sub = messagebox.askyesno(
            "Subpastas", "Incluir também as imagens das subpastas?")
        encontrados = []
        if incluir_sub:
            for dirpath, _, nomes in os.walk(pasta):
                for n in sorted(nomes):
                    encontrados.append(os.path.join(dirpath, n))
        else:
            for n in sorted(os.listdir(pasta)):
                encontrados.append(os.path.join(pasta, n))
        encontrados = [c for c in encontrados if os.path.isfile(c) and self._aceita(c)]
        if not encontrados:
            messagebox.showinfo("Nenhuma imagem",
                                "Nenhum arquivo dos formatos de entrada marcados foi encontrado.")
        self._adicionar(encontrados)

    def _adicionar(self, caminhos):
        existentes = set(self.arquivos)
        recusados = 0
        for c in caminhos:
            c = os.path.normpath(c)
            if not self._aceita(c):
                recusados += 1
                continue
            if c not in existentes:
                self.arquivos.append(c)
                self.lista.insert("end", c)
                existentes.add(c)
        self._atualizar_contagem(recusados)

    def remover_selecionados(self):
        for i in reversed(self.lista.curselection()):
            self.lista.delete(i)
            del self.arquivos[i]
        self._atualizar_contagem()

    def limpar_lista(self):
        if self.convertendo:
            return
        self.lista.delete(0, "end")
        self.arquivos.clear()
        self._atualizar_contagem()

    def _atualizar_contagem(self, recusados=0):
        texto = f"{len(self.arquivos)} arquivo(s)"
        if recusados:
            texto += f"  ({recusados} fora dos formatos de entrada marcados, não adicionado(s))"
        self.lbl_contagem.config(text=texto)

    # ---------------------------- opções --------------------------------
    def _atualizar_pasta(self):
        estado = "disabled" if self.var_mesma_pasta.get() else "normal"
        self.ent_saida.config(state=estado)
        self.btn_saida.config(state=estado)

    def escolher_saida(self):
        pasta = filedialog.askdirectory(title="Pasta de saída")
        if pasta:
            self.var_pasta_saida.set(pasta)

    def _ao_mudar_qualidade(self, valor):
        v = int(float(valor))
        self.var_qualidade.set(v)
        self.lbl_q.config(text=str(v))

    def escolher_cor(self):
        rgb, hexa = colorchooser.askcolor(color="#%02x%02x%02x" % self.cor_fundo,
                                          title="Cor de fundo")
        if rgb:
            self.cor_fundo = tuple(int(c) for c in rgb)
            self.amostra.config(bg=hexa)

    # ---------------------------- conversão -----------------------------
    def iniciar(self):
        if self.convertendo:
            return
        if not self.arquivos:
            messagebox.showwarning("Atenção", "Adicione ao menos uma imagem.")
            return
        try:
            largura_svg = int(float(self.var_svg.get()))
        except ValueError:
            messagebox.showwarning("Atenção", "A largura do SVG precisa ser um número.")
            return
        largura_svg = max(16, min(16384, largura_svg))

        if not self.var_mesma_pasta.get():
            pasta = self.var_pasta_saida.get().strip()
            if not pasta:
                messagebox.showwarning("Atenção", "Escolha a pasta de saída.")
                return
            try:
                os.makedirs(pasta, exist_ok=True)
            except OSError as e:
                messagebox.showerror("Erro", f"Não foi possível criar a pasta:\n{e}")
                return

        self.convertendo = True
        self.cancelar = False
        self.btn_converter.config(state="disabled")
        self.btn_cancelar.config(state="normal")
        self.progresso.config(maximum=len(self.arquivos), value=0)
        self.lbl_prog.config(text=f"0/{len(self.arquivos)}")
        self._limpar_log()

        config = dict(
            arquivos=list(self.arquivos),
            formato=self._fmt_saida(),
            mesma_pasta=self.var_mesma_pasta.get(),
            pasta_saida=self.var_pasta_saida.get().strip(),
            existente=self.var_existente.get(),
            opcoes=dict(
                qualidade=self.var_qualidade.get(),
                sem_perdas=self.var_sem_perdas.get(),
                fundo=self.cor_fundo,
                metadados=self.var_metadados.get(),
                otimizar=self.var_otimizar.get(),
                largura_svg=largura_svg,
            ),
        )
        threading.Thread(target=self._trabalhar, args=(config,), daemon=True).start()

    def cancelar_conversao(self):
        self.cancelar = True
        self.btn_cancelar.config(state="disabled")

    def _trabalhar(self, cfg):
        ok = erros = ignorados = 0
        total = len(cfg["arquivos"])
        fmt = cfg["formato"]
        ext_saida = FORMATOS[fmt]["ext_saida"]
        usados = set()  # destinos gravados nesta rodada (evita sobrescrever entre si)

        for i, origem in enumerate(cfg["arquivos"], start=1):
            if self.cancelar:
                self.fila.put(("log", "Cancelado pelo usuário."))
                break
            destino = None
            criado_agora = False
            try:
                nome_origem = os.path.basename(origem)
                if formato_do_arquivo(origem) == fmt:
                    ignorados += 1
                    self.fila.put(("log", f"IGNORADO (já está em {FORMATOS[fmt]['rotulo']}): {nome_origem}"))
                    self.fila.put(("prog", i, total))
                    continue

                pasta = os.path.dirname(origem) if cfg["mesma_pasta"] else cfg["pasta_saida"]
                destino = os.path.join(pasta, os.path.splitext(nome_origem)[0] + ext_saida)

                if os.path.exists(destino):
                    politica = cfg["existente"]
                    if os.path.normcase(destino) in usados and politica == "sobrescrever":
                        politica = "renomear"  # não apaga o que acabou de ser gerado
                    if politica == "ignorar":
                        ignorados += 1
                        self.fila.put(("log", f"IGNORADO (já existe): {os.path.basename(destino)}"))
                        self.fila.put(("prog", i, total))
                        continue
                    if politica == "renomear":
                        destino = caminho_livre(destino)
                criado_agora = not os.path.exists(destino)
                usados.add(os.path.normcase(destino))

                converter_imagem(origem, destino, fmt, cfg["opcoes"])
                ok += 1
                antes = os.path.getsize(origem) / 1024
                depois = os.path.getsize(destino) / 1024
                self.fila.put(("log",
                               f"OK: {nome_origem} → {os.path.basename(destino)} "
                               f"({antes:.0f} KB → {depois:.0f} KB)"))
            except Exception as e:
                erros += 1
                if destino and criado_agora and os.path.exists(destino):
                    try:
                        os.remove(destino)  # não deixa arquivo pela metade
                    except OSError:
                        pass
                self.fila.put(("log", f"ERRO em {os.path.basename(origem)}: {e}"))
            self.fila.put(("prog", i, total))

        self.fila.put(("fim", ok, erros, ignorados))

    def _processar_fila(self):
        try:
            while True:
                msg = self.fila.get_nowait()
                if msg[0] == "log":
                    self._escrever_log(msg[1])
                elif msg[0] == "prog":
                    self.progresso.config(value=msg[1])
                    self.lbl_prog.config(text=f"{msg[1]}/{msg[2]}")
                elif msg[0] == "fim":
                    _, ok, erros, ign = msg
                    self.convertendo = False
                    self.btn_converter.config(state="normal")
                    self.btn_cancelar.config(state="disabled")
                    resumo = f"Concluído: {ok} convertido(s), {erros} erro(s), {ign} ignorado(s)."
                    self._escrever_log(resumo)
                    messagebox.showinfo("Conversão finalizada", resumo)
        except queue.Empty:
            pass
        self.after(100, self._processar_fila)

    # ---------------------------- log -----------------------------------
    def _escrever_log(self, texto):
        self.log.config(state="normal")
        self.log.insert("end", texto + "\n")
        self.log.see("end")
        self.log.config(state="disabled")

    def _limpar_log(self):
        self.log.config(state="normal")
        self.log.delete("1.0", "end")
        self.log.config(state="disabled")


if __name__ == "__main__":
    App().mainloop()
