@echo off
REM ---------------------------------------------------------------------------
REM Deja el servicio web de consulta escuchando en el puerto 8000.
REM
REM Lo invoca la tarea programada "TesisBackend". Existe por el mismo motivo que
REM el del capturador: lanzado desde una sesion de trabajo, el proceso muere
REM cuando esa sesion termina. El 2026-09-02 se cayo tres veces mientras se
REM trabajaba, y cada caida deja el tablero sin datos en vivo.
REM
REM Usa el interprete del ENTORNO VIRTUAL. Con el del sistema falta la mitad de
REM las dependencias, que es lo que dejo una carrera entera grabada sin publicar.
REM
REM PARA APAGARLO, ver scripts\desactivar_servicios.ps1
REM ---------------------------------------------------------------------------

REM La raiz sale de la ubicacion de este archivo ---`%~dp0` es la carpeta
REM `scripts\`--- y no de una ruta escrita a mano. Estaba fija en
REM `C:\Users\Usuario\Documents\GitHub\tesis`, que es la ruta de UNA maquina:
REM en cualquier otra, o con el repositorio en otra carpeta, el servicio
REM arranca y no encuentra nada.
for %%I in ("%~dp0..") do set RAIZ=%%~fI
set PYTHON=%RAIZ%\.venv\Scripts\python.exe
set REGISTRO=%RAIZ%\logs\backend.log

if not exist "%RAIZ%\logs" mkdir "%RAIZ%\logs"

cd /d "%RAIZ%"

echo. >> "%REGISTRO%"
echo ===== arranque %DATE% %TIME% ===== >> "%REGISTRO%"

REM -u deja la salida sin buffer: un registro que se pierde al morir el proceso
REM no sirve para averiguar por que murio.
"%PYTHON%" -u -m uvicorn backend.app:app --host 127.0.0.1 --port 8000 >> "%REGISTRO%" 2>&1

echo ===== salida con codigo %ERRORLEVEL% el %DATE% %TIME% ===== >> "%REGISTRO%"
