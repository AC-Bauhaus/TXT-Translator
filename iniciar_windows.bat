@echo off
setlocal EnableExtensions
cd /d "%~dp0"
title TXT Translator - Web Local

echo ========================================
echo       TXT Translator - Web Local
echo ========================================
echo.

REM ========================================
REM Localiza o Python instalado no sistema
REM ========================================

set "PY_CMD="

where python >nul 2>&1
if not errorlevel 1 (
    python --version
    if not errorlevel 1 (
        set "PY_CMD=python"
        goto python_selected
    )
)

where py >nul 2>&1
if not errorlevel 1 (
    py --version
    if not errorlevel 1 (
        set "PY_CMD=py"
        goto python_selected
    )
)

echo.
echo ERRO: Python nao foi encontrado.
echo.
echo Verifique se o Python esta instalado e configurado no PATH.
echo.
pause
exit /b 1

:python_selected

echo.
echo Python selecionado:
%PY_CMD% --version
echo.

REM ========================================
REM Verifica se o start_web.py existe
REM ========================================

if not exist "start_web.py" (
    echo.
    echo ERRO: o arquivo start_web.py nao foi encontrado.
    echo.
    echo Pasta atual:
    echo %cd%
    echo.
    pause
    exit /b 1
)

REM ========================================
REM Verifica o pip
REM ========================================

echo.
echo [1/2] Verificando pip...

%PY_CMD% -m pip --version >nul 2>&1

if errorlevel 1 (
    echo.
    echo ERRO: o pip nao esta disponivel neste Python.
    echo.
    echo Tente executar:
    echo %PY_CMD% -m ensurepip --upgrade
    echo.
    pause
    exit /b 1
)

echo Pip encontrado.
echo.

REM ========================================
REM Instala/verifica as dependencias
REM ========================================

if exist "requirements.txt" (

    echo [2/2] Verificando dependencias...
    echo.

    %PY_CMD% -m pip install -r requirements.txt >nul 2>&1

    if errorlevel 1 (
        echo.
        echo ========================================
        echo ERRO ao instalar as dependencias.
        echo ========================================
        echo.
        pause
        exit /b 1
    )

) else (

    echo.
    echo AVISO: requirements.txt nao foi encontrado.
    echo Continuando mesmo assim...
    echo.

)

REM ========================================
REM Inicia o servidor
REM ========================================

echo.
echo ========================================
echo       Iniciando servidor...
echo ========================================
echo.

%PY_CMD% start_web.py

set "EXIT_CODE=%ERRORLEVEL%"

echo.

if "%EXIT_CODE%"=="0" (
    echo ========================================
    echo O servidor foi encerrado normalmente.
    echo ========================================
) else (
    echo ========================================
    echo ERRO ao executar start_web.py
    echo Codigo de saida: %EXIT_CODE%
    echo ========================================
)

echo.
pause
exit /b %EXIT_CODE%