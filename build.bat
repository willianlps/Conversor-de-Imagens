@echo off
cd /d "%~dp0"
echo ==============================================
echo  Gerando ConversorImagens.exe
echo ==============================================
echo.

where python >nul 2>nul
if errorlevel 1 (
    echo ERRO: Python nao encontrado.
    echo Instale em https://www.python.org/downloads/ e marque "Add Python to PATH".
    pause
    exit /b 1
)

if not exist conversor_imagens.py (
    echo ERRO: conversor_imagens.py nao esta na mesma pasta deste arquivo.
    pause
    exit /b 1
)

echo [1/2] Instalando dependencias...
python -m pip install --upgrade pip "pillow>=11.3" pymupdf pyinstaller
if errorlevel 1 (
    echo ERRO ao instalar as dependencias.
    pause
    exit /b 1
)

echo.
echo [2/2] Criando o executavel...
if exist icone.ico (
    python -m PyInstaller --onefile --windowed --clean --noconfirm --name ConversorImagens --collect-all pymupdf --icon=icone.ico conversor_imagens.py
) else (
    python -m PyInstaller --onefile --windowed --clean --noconfirm --name ConversorImagens --collect-all pymupdf conversor_imagens.py
)
if errorlevel 1 (
    echo ERRO ao gerar o executavel.
    pause
    exit /b 1
)

echo.
echo ==============================================
echo  Pronto! Seu programa esta em:
echo  %~dp0dist\ConversorImagens.exe
echo ==============================================
explorer "%~dp0dist"
pause
