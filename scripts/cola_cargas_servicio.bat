@echo off
REM ---------------------------------------------------------------------------
REM Retoma la cola de cargas de telemetria OpenF1.
REM
REM Lo invoca la tarea programada "TesisColaCargas". A diferencia de las otras
REM dos, **esta tarea es temporal**: existe para terminar las cargas pendientes y
REM deja de tener sentido cuando terminan. El guion detecta lo que ya esta
REM completo y sale enseguida, de modo que dejarla no rompe nada, pero conviene
REM quitarla igual.
REM
REM Espera antes de arrancar. Las cargas necesitan el intermediario de mensajes y
REM la base, que corren en contenedores: al iniciar sesion, el entorno de
REM contenedores todavia puede estar levantandose y la carga fallaria por no
REM encontrarlos.
REM
REM PARA APAGARLA, ver scripts\desactivar_servicios.ps1
REM ---------------------------------------------------------------------------

set RAIZ=C:\Users\Usuario\Documents\GitHub\tesis
set PYTHON=%RAIZ%\.venv\Scripts\python.exe
set REGISTRO=%RAIZ%\logs\cola_cargas.log

if not exist "%RAIZ%\logs" mkdir "%RAIZ%\logs"

cd /d "%RAIZ%"

echo. >> "%REGISTRO%"
echo ===== arranque %DATE% %TIME% ===== >> "%REGISTRO%"

REM Noventa segundos para que el entorno de contenedores termine de levantar.
timeout /t 90 /nobreak > nul

"%PYTHON%" -u scripts\encolar_cargas_openf1.py >> "%REGISTRO%" 2>&1

echo ===== salida con codigo %ERRORLEVEL% el %DATE% %TIME% ===== >> "%REGISTRO%"
