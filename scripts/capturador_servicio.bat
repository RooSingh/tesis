@echo off
REM ---------------------------------------------------------------------------
REM Deja el capturador de telemetria F1 25 escuchando el puerto 20777.
REM
REM Existe porque el capturador esta pensado para vivir indefinidamente ---su
REM propia documentacion dice "queda escuchando y captura solo lo que vaya
REM pasando"--- y lanzarlo desde una sesion de trabajo no cumple esa promesa: el
REM proceso muere cuando esa sesion termina. El 2026-09-02 murio cuatro veces, y
REM una de ellas ocurrio justo antes de una carrera.
REM
REM Lo invoca la tarea programada "TesisCapturadorF1_25", que arranca al iniciar
REM sesion en Windows.
REM
REM PARA APAGARLO CUANDO EL PROYECTO TERMINE, ver scripts\desactivar_capturador.ps1
REM ---------------------------------------------------------------------------

set RAIZ=C:\Users\Usuario\Documents\GitHub\tesis
REM El interprete del ENTORNO VIRTUAL, no el del sistema.
REM
REM Con el del sistema el capturador arranca y graba, pero no puede publicar:
REM paho-mqtt esta instalado en el entorno del proyecto y no fuera de el. La
REM captura de Spa del 2026-09-02 quedo grabada entera y sin publicar un solo
REM mensaje, y sus propios metadatos lo declararon:
REM   "broker no disponible: ModuleNotFoundError"
set PYTHON=%RAIZ%\.venv\Scripts\python.exe
set REGISTRO=%RAIZ%\logs\capturador.log

if not exist "%RAIZ%\logs" mkdir "%RAIZ%\logs"

cd /d "%RAIZ%"

REM El registro se conserva entre arranques: si el proceso vuelve a morir sin
REM dejar rastro, la unica forma de saberlo es comparar marcas de arranque.
echo. >> "%REGISTRO%"
echo ===== arranque %DATE% %TIME% ===== >> "%REGISTRO%"

REM -u deja la salida sin buffer. Un registro que se pierde cuando el proceso
REM muere no sirve para averiguar por que murio, que fue justo lo que paso.
"%PYTHON%" -u scripts\capturar_f1_25.py >> "%REGISTRO%" 2>&1

echo ===== salida con codigo %ERRORLEVEL% el %DATE% %TIME% ===== >> "%REGISTRO%"
