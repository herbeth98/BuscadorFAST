<#
  Chamado pelo desinstalador: fecha o BuscadorFAST desta pasta e tira as tarefas da atualização noturna
  que apontam para ela. Os arquivos são apagados pelo próprio desinstalador.
#>
param([string]$Pasta = (Split-Path -Parent $PSScriptRoot))
$ErrorActionPreference = "Continue"

$venv = Join-Path $Pasta ".venv"
$procs = @(Get-CimInstance Win32_Process -Filter "Name='pythonw.exe' OR Name='python.exe'" -ErrorAction SilentlyContinue |
    Where-Object { $_.ExecutablePath -and $_.ExecutablePath.StartsWith($venv, [StringComparison]::OrdinalIgnoreCase) })
if ($procs.Count) {
    try { Invoke-WebRequest -UseBasicParsing -Method Post "http://127.0.0.1:8765/api/sair" -TimeoutSec 5 | Out-Null } catch { }
    Start-Sleep -Seconds 3
    $procs | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
}

foreach ($nome in @("BuscadorFAST\Atualizar", "BuscadorFAST\Parar")) {
    $xml = schtasks /Query /TN $nome /XML 2>$null
    if ($LASTEXITCODE -eq 0 -and ($xml -join "`n").ToLower().Contains($Pasta.ToLower())) {
        schtasks /Delete /TN $nome /F | Out-Null
    }
}
exit 0
