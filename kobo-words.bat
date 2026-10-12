@echo off
rem ------------------------------------------------------------------
rem  kobo-words: exporta las palabras del Kobo y las sube a Notion.
rem  Doble clic para ejecutar. Debe estar en la carpeta del proyecto.
rem ------------------------------------------------------------------
title kobo-words
cd /d "%~dp0"

rem Para que se vean bien tildes y emojis en la consola
chcp 65001 >nul
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8

set PY=.venv\Scripts\python.exe
if not exist "%PY%" (
    echo No encuentro el entorno virtual en "%~dp0.venv".
    echo Crealo una vez con:
    echo     python -m venv .venv
    echo     .venv\Scripts\python.exe -m pip install -r requirements.txt
    goto fin
)

echo.
echo === Exportando palabras del Kobo y subiendolas a Notion ===
echo.
"%PY%" -m kobo_words todo
if errorlevel 1 (
    echo.
    echo Algo ha fallado. Revisando la configuracion...
    echo.
    "%PY%" -m kobo_words comprobar
    goto fin
)

echo.
set /p LIMPIAR="Quieres borrar del Kobo las palabras ya exportadas? (s/N): "
if /i "%LIMPIAR%"=="s" (
    echo.
    "%PY%" -m kobo_words limpiar-kobo --si
)

echo.
echo Listo. Recuerda expulsar el Kobo antes de desconectarlo.

:fin
echo.
pause
