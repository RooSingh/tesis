# ---------------------------------------------------------------------------
# Deja corriendo de forma permanente los servicios del trabajo.
#
# POR QUE EXISTE
# --------------
# Los tres procesos estan pensados para vivir indefinidamente, y ninguno lo hacia
# cuando se lanzaba desde una sesion de trabajo: mueren con esa sesion. El
# 2026-09-02 el capturador se cayo cuatro veces ---una de ellas justo antes de
# largar una carrera--- y el servicio web tres. Windows los sostiene; una sesion
# de trabajo no.
#
# QUE REGISTRA
# ------------
#   TesisCapturadorF1_25   escucha el puerto UDP 20777 y guarda una captura por
#                          sesion de juego
#   TesisBackend           el servicio web de consulta, en el puerto 8000
#   TesisColaCargas        TEMPORAL: termina las cargas de telemetria pendientes
#
# COMO USARLO
# -----------
#     powershell -ExecutionPolicy Bypass -File scripts\activar_servicios.ps1
#
# Se puede correr las veces que haga falta: reemplaza lo que ya estuviera
# registrado en lugar de fallar.
#
# PARA APAGARLOS AL TERMINAR EL PROYECTO
# --------------------------------------
#     powershell -ExecutionPolicy Bypass -File scripts\desactivar_servicios.ps1
# ---------------------------------------------------------------------------

param(
    # Que servicios registrar. Por omision, los tres.
    [string[]]$Servicios = @("capturador", "backend", "cola")
)

$Raiz = "C:\Users\Usuario\Documents\GitHub\tesis"

$Definiciones = @{
    "capturador" = @{
        Tarea = "TesisCapturadorF1_25"
        Bat   = "scripts\capturador_servicio.bat"
        Que   = "Capturador de telemetria F1 25. Escucha el puerto UDP 20777 y guarda una captura por sesion de juego."
        Temporal = $false
    }
    "backend" = @{
        Tarea = "TesisBackend"
        Bat   = "scripts\backend_servicio.bat"
        Que   = "Servicio web de consulta del trabajo, en el puerto 8000. Alimenta el tablero."
        Temporal = $false
    }
    "cola" = @{
        Tarea = "TesisColaCargas"
        Bat   = "scripts\cola_cargas_servicio.bat"
        Que   = "TEMPORAL. Termina las cargas de telemetria OpenF1 pendientes. Se puede quitar en cuanto terminen."
        Temporal = $true
    }
}

foreach ($clave in $Servicios) {
    $d = $Definiciones[$clave]
    if (-not $d) {
        Write-Warning "Servicio desconocido: $clave"
        continue
    }

    $bat = Join-Path $Raiz $d.Bat
    if (-not (Test-Path $bat)) {
        Write-Warning "$($d.Tarea): no se encuentra $bat"
        continue
    }

    if (Get-ScheduledTask -TaskName $d.Tarea -ErrorAction SilentlyContinue) {
        Unregister-ScheduledTask -TaskName $d.Tarea -Confirm:$false
    }

    $accion = New-ScheduledTaskAction -Execute $bat -WorkingDirectory $Raiz
    $disparador = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME

    # Sin limite de duracion: un servicio que se apaga solo a las 72 horas es
    # justamente el problema que estas tareas vienen a resolver.
    $opciones = New-ScheduledTaskSettingsSet `
        -AllowStartIfOnBatteries `
        -DontStopIfGoingOnBatteries `
        -StartWhenAvailable `
        -RestartCount 3 `
        -RestartInterval (New-TimeSpan -Minutes 1) `
        -ExecutionTimeLimit (New-TimeSpan -Seconds 0)

    $aviso = if ($d.Temporal) {
        "ESTA TAREA ES TEMPORAL: quitala en cuanto las cargas terminen."
    } else {
        "DEJA DE SER NECESARIA cuando el proyecto termine."
    }

    $descripcion = @"
$($d.Que)

$aviso
Para apagarla:
  powershell -ExecutionPolicy Bypass -File $Raiz\scripts\desactivar_servicios.ps1

Registro: $Raiz\logs\
"@

    Register-ScheduledTask -TaskName $d.Tarea `
        -Action $accion `
        -Trigger $disparador `
        -Settings $opciones `
        -Description $descripcion `
        -RunLevel Limited | Out-Null

    Write-Host "Registrada: $($d.Tarea)"
    Start-ScheduledTask -TaskName $d.Tarea
}

Write-Host ""
Write-Host "Para apagarlos al terminar el proyecto:"
Write-Host "  powershell -ExecutionPolicy Bypass -File scripts\desactivar_servicios.ps1"
