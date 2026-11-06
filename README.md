# Conversor de Imagens

Programa para Windows (e qualquer sistema com Python) com interface gráfica para converter imagens entre vários formatos, em lote, sem precisar de internet.

## Formatos

| Entrada | Saída |
|---------|-------|
| PNG | PNG |
| JPG / JPEG | JPG |
| WebP | WebP |
| AVIF | AVIF |
| BMP | BMP |
| SVG | — |

Você escolhe quais formatos de entrada aceitar e para qual formato converter. O SVG funciona apenas como entrada, porque é um formato vetorial e é transformado em pixels.

## Recursos

- Conversão em lote: adicione arquivos avulsos ou uma pasta inteira, com ou sem subpastas
- Qualidade ajustável para JPG, WebP e AVIF (JPG usa cores 4:4:4 para evitar perda de nitidez nas cores)
- WebP sem perdas, que preserva cada pixel
- Transparência preservada em PNG, WebP e AVIF; em JPG e BMP ela é substituída pela cor de fundo que você escolher
- SVG rasterizado na largura em pixels que você definir
- Preserva perfil de cor ICC, EXIF e DPI quando o formato de saída permite
- Salvar ao lado dos originais ou em outra pasta
- Se o arquivo já existir: renomear, sobrescrever ou ignorar
- Barra de progresso, log de cada arquivo e botão de cancelar
- A conversão roda em segundo plano, então a janela não trava

## Como usar o programa pronto (Windows)

1. Baixe o `ConversorImagens.exe` na aba **Releases** deste repositório.
2. Dê um duplo clique. Não é preciso instalar Python.
3. Na primeira vez, o Windows pode mostrar "Windows protegeu seu computador", porque o executável não é assinado. Clique em **Mais informações** e depois em **Executar assim mesmo**.

## Como rodar pelo código

Requer Python 3.9 ou mais novo.

```
pip install "pillow>=11.3" pymupdf
python conversor_imagens.py
```

- O Pillow 11.3 ou mais novo é necessário para o AVIF.
- O PyMuPDF é necessário para ler SVG.
- Se alguma dessas bibliotecas faltar, o programa avisa na janela e desativa apenas o formato correspondente.

## Como gerar o .exe

No Windows, com o Python instalado (marque "Add Python to PATH" na instalação), coloque `conversor_imagens.py` e `build.bat` na mesma pasta e dê um duplo clique em `build.bat`.

O script instala as dependências e gera o `ConversorImagens.exe` na pasta `dist`. Se houver um arquivo `icone.ico` na mesma pasta, ele é usado como ícone do programa.

O PyInstaller não faz compilação cruzada: o `.exe` precisa ser gerado em um Windows.

## Observações sobre qualidade

- JPG, WebP (com perdas) e AVIF comprimem com perdas. Mesmo na qualidade 100, o arquivo não é matematicamente idêntico ao original, embora a diferença costume ser invisível a olho nu.
- Converter uma imagem que já tem perdas (JPG, WebP ou AVIF) para outro formato com perdas causa uma perda extra.
- Para preservar tudo, use PNG ou WebP sem perdas como saída.
- Arquivos que já estão no formato de saída são ignorados, para evitar recompressão desnecessária.
- Em imagens animadas, só o primeiro quadro é convertido.


Defina aqui a licença do projeto (por exemplo, MIT).
