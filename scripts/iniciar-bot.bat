@echo off
chcp 65001 >nul
title Job Search Bot - escuchando

rem Lanzador del bot de Telegram. El acceso directo del escritorio apunta aqui.
rem Sin acentos a proposito: cmd.exe los rompe segun la codificacion del sistema.

cd /d "%~dp0.."

if not exist ".env" goto :sin_env

set "TOKEN="
set "CHATID="
for /f "usebackq tokens=2 delims==" %%A in (`findstr /b /c:"TELEGRAM_BOT_TOKEN=" .env`) do set "TOKEN=%%A"
for /f "usebackq tokens=2 delims==" %%A in (`findstr /b /c:"TELEGRAM_CHAT_ID=" .env`) do set "CHATID=%%A"

if not defined TOKEN goto :sin_credenciales
if not defined CHATID goto :sin_credenciales

set "JOBBOT=jobbot"
where jobbot >nul 2>nul || set "JOBBOT=python -m jobbot.cli"

echo.
echo  Bot arrancando. Escribele desde Telegram: /ayuda
echo  Para pararlo, cierra esta ventana o pulsa Ctrl+C.
echo.

%JOBBOT% bot

echo.
echo  El bot se ha detenido.
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

:sin_credenciales
echo.
echo  Faltan credenciales en .env. Necesitas rellenar estas dos lineas:
echo.
echo    TELEGRAM_BOT_TOKEN=   (te lo da @BotFather con /newbot)
echo    TELEGRAM_CHAT_ID=     (escribe a tu bot y ejecuta: jobbot chat-id)
echo.
echo  El fichero esta en:
echo    %CD%\.env
echo.
pause
exit /b 1
