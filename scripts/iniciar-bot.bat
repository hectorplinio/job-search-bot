@echo off
chcp 65001 >nul
title Job Search Bot - escuchando

rem Lanzador del bot de Telegram. El acceso directo del escritorio apunta aqui,
rem y tambien el de la carpeta de Inicio de Windows.
rem
rem El bot hace dos cosas: atiende tus comandos y botones, y lanza la busqueda
rem cada X horas (seccion schedule de config.yaml). Por eso se relanza solo si
rem se cae: si muere el proceso, se acaban las busquedas.
rem
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
echo  Busca ofertas solo, cada pocas horas. Dejalo abierto.
echo  Para pararlo del todo, cierra esta ventana.
echo.

:bucle
%JOBBOT% bot
rem Un Ctrl+C sale con 0 o 130 y significa que paras tu: no relanzamos.
if "%ERRORLEVEL%"=="0" goto :parado
if "%ERRORLEVEL%"=="130" goto :parado
echo.
echo  El bot se ha caido (codigo %ERRORLEVEL%). Relanzando en 15 segundos...
timeout /t 15 /nobreak >nul
goto :bucle

:parado
echo.
echo  Bot detenido.
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
