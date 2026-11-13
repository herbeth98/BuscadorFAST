# Chamado pelo Agendador de Tarefas do Windows (criado em ⚙ → Atualização automática).
#   noturno.ps1 iniciar  → abre o BuscadorFAST se estiver fechado e começa "Atualizar todos os discos"
#   noturno.ps1 parar    → para a tarefa em andamento (o que foi feito fica salvo; continua na próxima noite)
param([string]$acao = "iniciar")
$url = "http://127.0.0.1:8765"
$pasta = Split-Path -Parent $PSScriptRoot

function Vivo {
    try { Invoke-WebRequest -UseBasicParsing "$url/api/jobs" -TimeoutSec 3 | Out-Null; return $true } catch { return $false }
}

if ($acao -eq "parar") {
    if (Vivo) { Invoke-WebRequest -UseBasicParsing -Method Post "$url/api/cancel" -TimeoutSec 10 | Out-Null }
    exit 0
}

if (-not (Vivo)) {
    Start-Process (Join-Path $pasta "BuscadorFAST.exe")
    for ($i = 0; $i -lt 60 -and -not (Vivo); $i++) { Start-Sleep -Seconds 2 }
}
if (Vivo) {
    Invoke-WebRequest -UseBasicParsing -Method Post "$url/api/atualizar" -TimeoutSec 30 | Out-Null
    # depois da atualização: 3 h de teste de leitura dos discos (continua de onde parou na noite seguinte)
    Invoke-WebRequest -UseBasicParsing -Method Post "$url/api/leitura" -ContentType "application/json" -Body '{"horas": 3}' -TimeoutSec 30 | Out-Null
}
