# Imagen unica para los tres procesos de la aplicacion.
#
# POR QUE UNA Y NO TRES. El servicio web, el consumidor y el capturador son
# tres entradas del **mismo** codigo: importan `backend/`, comparten
# `requirements.txt` y se despliegan juntos. Tres imagenes serian tres copias
# del mismo arbol que hay que acordarse de reconstruir a la vez, y olvidarse de
# una deja dos versiones del contrato interno conviviendo, que es exactamente
# el estado que ninguna prueba declara. Lo que cambia entre los tres es el
# comando, y eso lo dice el compose.
#
# LA VERSION DE PYTHON ES LA DEL EQUIPO DE DESTINO. La Raspberry corre 3.13.5;
# el banco de trabajo, 3.12. Se fija la del destino porque es donde el sistema
# opera, y porque una diferencia de version que solo aparece en produccion es
# la peor clase de diferencia.
FROM python:3.13-slim

# `PYTHONUNBUFFERED` para que lo que el proceso imprima salga cuando ocurre y
# no cuando se llene un buffer: el registro de un servicio que se lee en vivo
# no sirve si llega en bloques. `PYTHONDONTWRITEBYTECODE` para no ensuciar el
# arbol montado con `__pycache__` que pertenece a otra version de Python.
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# LAS DEPENDENCIAS ANTES QUE EL CODIGO, a proposito. Docker cachea por capa: si
# se copiara todo junto, cambiar una linea de `app.js` obligaria a reinstalar
# las sesenta y nueve dependencias. Asi, un cambio de codigo reconstruye una
# capa de segundos y no una de minutos, que en una Raspberry es la diferencia
# entre desplegar y no desplegar.
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# El arbol del proyecto. `.dockerignore` decide que no entra: las capturas
# crudas son 1,6 GB y no tienen nada que hacer dentro de una imagen.
COPY . .

# NO SE DECLARA UN `CMD`. Los tres servicios lo declaran en el compose, y poner
# uno aca dejaria que un `docker run` sin argumentos arranque algo que nadie
# pidio. Una imagen que no sabe sola que hacer es mas segura que una que
# adivina.
