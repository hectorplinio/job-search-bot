@echo off
chcp 65001 >nul
title Job Search Bot - buscando ofertas

rem Una pasada de busqueda y cierra. Es lo mismo que ejecuta la tarea
rem programada. Util para lanzarla a mano cuando te apetece mirar.

cd /d "%~dp0.."

if not exist ".env" goto :sin_env

set "TOKEN="
for /f "usebackq tokens=2 delims==" %%A in (`findstr /b /c:"TELEGRAM_BOT_TOKEN=" .env`) do set "TOKEN=%%A"

set "JOBBOT=jobbot"
where jobbot >nul 2>nul || set "JOBBOT=python -m jobbot.cli"

if not defined TOKEN (
    echo.
    echo  Sin TELEGRAM_BOT_TOKEN en .env: hago la busqueda igual, pero solo
    echo  se vera aqui en pantalla, sin mandar nada a Telegram.
    echo.
    %JOBBOT% run --dry-run
    goto :fin
)

%JOBBOT% run

:fin
echo.
pause
exit /b 0

:sin_env
echo.
echo  No encuentro el fichero .env en:
echo    %CD%
echo.
echo  Copia .env.example a .env y rellenalo.
echo.
pause
exit /b 1
