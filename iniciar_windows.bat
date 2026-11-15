@echo off
setlocal EnableExtensions
cd /d "%~dp0"
title TXT Translator - Web Local

echo ========================================
echo       TXT Translator - Web Local
echo ========================================
echo.

REM Argos Translate dependency stack is most reliable on Python 3.11/3.12.
REM Prefer 3.12, then 3.11. Python 3.15 may force PyYAML source compilation.
set "PY_CMD="
where py >nul 2>&1
if not errorlevel 1 (
    py -3.12 --version >nul 2>&1
    if not errorlevel 1 (
        set "PY_CMD=py -3.12"
        goto python_selected
    )
    py -3.11 --version >nul 2>&1
    if not errorlevel 1 (
        set "PY_CMD=py -3.11"
        goto python_selected
    )
)

where python >nul 2>&1
if not errorlevel 1 (
    python -c "import sys; raise SystemExit(0 if sys.version_info[:2] in ((3,11),(3,12)) else 1)" >nul 2>&1
    if not errorlevel 1 set "PY_CMD=python"
)

if not defined PY_CMD (
    echo ERRO: Python 3.11 ou 3.12 nao foi encontrado.
    echo.
    echo Seu Python 3.15 nao e recomendado para esta versao do Argos Translate.
    echo Instale Python 3.12 (64-bit) e marque Add Python to PATH.
    echo Download: https://www.python.org/downloads/windows/
    echo Depois, execute este arquivo novamente.
    goto failed
)

:python_selected
echo Python selecionado:
%PY_CMD% --version
echo.

REM Recreate a virtual environment created with an unsupported Python version.
if exist ".venv\Scripts\python.exe" (
    ".venv\Scripts\python.exe" -c "import sys; raise SystemExit(0 if sys.version_info[:2] in ((3,11),(3,12)) else 1)" >nul 2>&1
    if errorlevel 1 (
        echo [1/3] Removendo ambiente virtual antigo/incompativel...
        rmdir /s /q ".venv"
        if exist ".venv" (
            echo ERRO: Nao foi possivel remover a pasta .venv.
            echo Feche programas que estejam usando arquivos dessa pasta e tente novamente.
            goto failed
        )
    )
)

if not exist ".venv\Scripts\python.exe" (
    echo [1/3] Criando ambiente virtual com Python 3.11/3.12...
    %PY_CMD% -m venv .venv
    if errorlevel 1 goto failed
)

if not exist ".venv\.dependencies-installed" (
    echo [2/3] Atualizando pip...
    ".venv\Scripts\python.exe" -m pip install --upgrade pip
    if errorlevel 1 goto failed

    echo [2/3] Instalando dependencias e usando wheel binario do PyYAML...
    ".venv\Scripts\python.exe" -m pip install --only-binary=PyYAML -r requirements.txt
    if errorlevel 1 goto failed
    >".venv\.dependencies-installed" echo ok
) else (
    echo [2/3] Dependencias ja instaladas.
)

echo.
echo [3/3] Iniciando servidor local...
echo Quando aparecer o endereco, abra http://127.0.0.1:5000/
echo Para encerrar, pressione Ctrl+C.
echo.
".venv\Scripts\python.exe" start_web.py
if errorlevel 1 goto failed

echo.
echo O servidor foi encerrado.
echo.
pause
exit /b 0

:failed
echo.
echo ========================================
echo Ocorreu um erro ao iniciar o TXT Translator.
echo A janela ficara aberta para voce ler a mensagem acima.
echo ========================================
echo.
pause
exit /b 1
