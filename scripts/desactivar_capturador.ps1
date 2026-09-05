# ---------------------------------------------------------------------------
# Este guion se reemplazo por uno que maneja los tres servicios.
#
# Se conserva porque el protocolo y la descripcion de la tarea programada lo
# nombran, y porque alguien puede tener el comando anotado. Redirige en lugar de
# fallar: un guion que existe y no hace nada es peor que uno que no existe.
#
# Para apagar TODO ---capturador, servicio web y cola de cargas:
#     powershell -ExecutionPolicy Bypass -File scripts\desactivar_servicios.ps1
# ---------------------------------------------------------------------------

Write-Host "Este guion se reemplazo por scripts\desactivar_servicios.ps1,"
Write-Host "que apaga el capturador, el servicio web y la cola de cargas."
Write-Host ""
Write-Host "Apagando solo el capturador, como hacia este..."
Write-Host ""

& "$PSScriptRoot\desactivar_servicios.ps1" -Servicios capturador
