# ---------------------------------------------------------------------------
# Apaga los servicios permanentes del trabajo.
#
# CUANDO USAR ESTO
# ----------------
# Al terminar el proyecto, o en cualquier momento en que ya no se vaya a
# capturar ni consultar. Mientras las tareas existan, la computadora queda con
# procesos escuchando en cada inicio de sesion aunque nadie los use.
#
# No son peligrosos ---escuchan en la interfaz local, no abren nada hacia afuera
# y solo escriben dentro del repositorio--- pero un proceso que ya no cumple
# ninguna funcion no tiene por que seguir corriendo.
#
# La cola de cargas se puede apagar antes que las otras dos: es temporal y deja
# de tener sentido en cuanto las cargas pendientes terminan.
#
# QUE HACE
# --------
# 1. Detiene los procesos que esten escuchando en los puertos del trabajo.
# 2. Elimina las tareas programadas, de modo que no vuelvan a arrancar.
# 3. Deja los registros y los guiones en su lugar, por si hiciera falta
#    revisarlos.
#
# COMO USARLO
# -----------
#     powershell -ExecutionPolicy Bypass -File scripts\desactivar_servicios.ps1
#
# Para apagar solo uno:
#     powershell -ExecutionPolicy Bypass -File scripts\desactivar_servicios.ps1 -Servicios cola
#
# Para volver a activarlos:
#     powershell -ExecutionPolicy Bypass -File scripts\activar_servicios.ps1
# ---------------------------------------------------------------------------

param(
    [string[]]$Servicios = @("capturador", "backend", "cola")
)

$Tareas = @{
    "capturador" = "TesisCapturadorF1_25"
    "backend"    = "TesisBackend"
    "cola"       = "TesisColaCargas"
}

# El capturador escucha por UDP y el servicio web por TCP: se buscan distinto.
Write-Host "Deteniendo procesos..."
if ($Servicios -contains "capturador") {
    $udp = Get-NetUDPEndpoint -LocalPort 20777 -ErrorAction SilentlyContinue
    foreach ($p in $udp) {
        try {
            Stop-Process -Id $p.OwningProcess -Force -ErrorAction Stop
            Write-Host "  capturador detenido (proceso $($p.OwningProcess))"
        } catch { }
    }
}
if ($Servicios -contains "backend") {
    $tcp = Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue
    foreach ($p in $tcp) {
        try {
            Stop-Process -Id $p.OwningProcess -Force -ErrorAction Stop
            Write-Host "  servicio web detenido (proceso $($p.OwningProcess))"
        } catch { }
    }
}
if ($Servicios -contains "cola") {
    Get-CimInstance Win32_Process -Filter "Name='python.exe'" |
        Where-Object { $_.CommandLine -like "*encolar_cargas*" -or $_.CommandLine -like "*replay_openf1*" } |
        ForEach-Object {
            try {
                Stop-Process -Id $_.ProcessId -Force -ErrorAction Stop
                Write-Host "  cola de cargas detenida (proceso $($_.ProcessId))"
            } catch { }
        }
}

Write-Host "Eliminando tareas programadas..."
foreach ($clave in $Servicios) {
    $tarea = $Tareas[$clave]
    if (-not $tarea) { continue }
    if (Get-ScheduledTask -TaskName $tarea -ErrorAction SilentlyContinue) {
        Unregister-ScheduledTask -TaskName $tarea -Confirm:$false
        Write-Host "  $tarea eliminada"
    } else {
        Write-Host "  $tarea no existia"
    }
}

Write-Host ""
Write-Host "Listo. Los registros se conservan en logs\ por si hace falta revisarlos."
