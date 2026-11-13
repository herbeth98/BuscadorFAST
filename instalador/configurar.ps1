<#
  Prepara o BuscadorFAST depois que os arquivos foram copiados. O instalador chama isto no fim.
  Também serve para quem baixou o código do GitHub. Na pasta do programa, rode:
      powershell -ExecutionPolicy Bypass -File instalador\configurar.ps1

  O que faz (rodar de novo só completa o que faltou):
    1. baixa o uv, que instala o Python e as bibliotecas, para a pasta tools
    2. instala o Python 3.12 só para o BuscadorFAST (não mexe em outro Python do computador)
    3. escolhe a IA certa para a placa de vídeo (NVIDIA com CUDA, ou o processador)
    4. instala as bibliotecas nas versões testadas (requirements-lock.txt)
    5. baixa o modelo de rostos e, com -Modelos, todos os modelos de IA (cerca de 12 GB)
#>
param(
    [string]$Pasta = (Split-Path -Parent $PSScriptRoot),
    [switch]$Modelos,
    [switch]$SemPausa
)
# "Continue": no Windows PowerShell 5.1, "Stop" transforma em erro qualquer aviso que o uv ou o Python escrevam
$ErrorActionPreference = "Continue"
$ProgressPreference = "SilentlyContinue"      # sem a barra, o Invoke-WebRequest baixa muito mais rápido
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
try { [Console]::OutputEncoding = [Text.Encoding]::UTF8 } catch { }
try { $Host.UI.RawUI.WindowTitle = "BuscadorFAST - preparando" } catch { }

$UV_VERSAO = "0.13.5"
$TORCH = @("torch==2.11.0", "torchvision==0.26.0")
$ONNX = "1.23.2"

function Titulo([string]$texto) { Write-Host ""; Write-Host "  $texto" -ForegroundColor Cyan }
function Ok([string]$texto) { Write-Host "     $texto" -ForegroundColor Green }
function Aviso([string]$texto) { Write-Host "     $texto" -ForegroundColor Yellow }
function Falha([string]$texto) {
    Write-Host ""
    Write-Host "  Não deu certo: $texto" -ForegroundColor Red
    Write-Host "  Confira a conexão com a internet e rode o instalador de novo: ele continua de onde parou." -ForegroundColor Red
    if (-not $SemPausa) { Read-Host "  Aperte Enter para fechar" | Out-Null }
    exit 1
}
function Rodar([string]$exe, [string[]]$argumentos, [string]$erro) {
    & $exe @argumentos
    if ($LASTEXITCODE -ne 0) { Falha $erro }
}

Write-Host ""
Write-Host "  BuscadorFAST" -ForegroundColor White
Write-Host "  Preparando o programa. São alguns gigabytes: pode levar de 10 a 40 minutos, conforme a internet."
Write-Host "  Pode deixar esta janela aberta e usar o computador normalmente."

$Pasta = (Resolve-Path $Pasta).Path
Set-Location $Pasta
$tools = Join-Path $Pasta "tools"
New-Item -ItemType Directory -Force $tools | Out-Null
$env:UV_PYTHON_INSTALL_DIR = Join-Path $tools "python"   # o Python fica dentro da pasta do programa
$env:UV_PYTHON_PREFERENCE = "only-managed"               # nunca usa outro Python que já exista no PC
$env:UV_LINK_MODE = "copy"
$cacheProprio = -not $env:UV_CACHE_DIR
if ($cacheProprio) { $env:UV_CACHE_DIR = Join-Path $tools "cache" }

# BuscadorFAST desta pasta aberto (atualização): fecha antes de trocar as bibliotecas
$venv = Join-Path $Pasta ".venv"
$rodando = @(Get-CimInstance Win32_Process -Filter "Name='pythonw.exe' OR Name='python.exe'" -ErrorAction SilentlyContinue |
    Where-Object { $_.ExecutablePath -and $_.ExecutablePath.StartsWith($venv, [StringComparison]::OrdinalIgnoreCase) })
if ($rodando.Count) {
    Titulo "Fechando o BuscadorFAST para atualizar"
    try { Invoke-WebRequest -UseBasicParsing -Method Post "http://127.0.0.1:8765/api/sair" -TimeoutSec 5 | Out-Null } catch { }
    Start-Sleep -Seconds 4
    $rodando | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
}

# 1. uv
Titulo "1/5  Baixando o uv (instalador de Python)"
$uv = Join-Path $tools "uv\uv.exe"
if (-not (Test-Path $uv)) {
    $zip = Join-Path $tools "uv.zip"
    $url = "https://github.com/astral-sh/uv/releases/download/$UV_VERSAO/uv-x86_64-pc-windows-msvc.zip"
    try { Invoke-WebRequest -UseBasicParsing $url -OutFile $zip -ErrorAction Stop } catch { Falha "não consegui baixar o uv ($url)" }
    try { Expand-Archive $zip -DestinationPath (Join-Path $tools "uv") -Force -ErrorAction Stop } catch { Falha "não consegui abrir o pacote do uv" }
    Remove-Item $zip
    $achado = Get-ChildItem (Join-Path $tools "uv") -Recurse -Filter "uv.exe" | Select-Object -First 1
    if (-not $achado) { Falha "o pacote do uv veio sem o uv.exe" }
    $uv = $achado.FullName
}
Ok "uv pronto"

# 2. Python 3.12 só para o programa
Titulo "2/5  Instalando o Python 3.12 (só para o BuscadorFAST)"
$py = Join-Path $venv "Scripts\python.exe"
if (-not (Test-Path $py)) {
    Rodar $uv @("venv", $venv, "--python", "3.12", "--clear") "não consegui instalar o Python"
}
Ok "Python pronto"

# 3. placa de vídeo
Titulo "3/5  Vendo a placa de vídeo"
$indice = "cpu"; $placa = ""; $cc = 0.0
$smi = Get-Command "nvidia-smi.exe" -ErrorAction SilentlyContinue
if ($smi) {
    try {
        $linha = & $smi.Source --query-gpu=name,compute_cap --format=csv,noheader 2>$null | Select-Object -First 1
        if ($LASTEXITCODE -eq 0 -and $linha) {
            $partes = $linha -split ","
            $placa = $partes[0].Trim()
            [double]::TryParse($partes[1].Trim(), [Globalization.NumberStyles]::Float, [Globalization.CultureInfo]::InvariantCulture, [ref]$cc) | Out-Null
        } else {
            $placa = (& $smi.Source --query-gpu=name --format=csv,noheader 2>$null | Select-Object -First 1)
            if ($placa) { $placa = $placa.Trim() }
        }
    } catch { }
}
if ($placa) {
    if ($cc -gt 0 -and $cc -lt 7.5) { $indice = "cu126" } else { $indice = "cu128" }
    Ok "Placa NVIDIA: $placa. A IA vai usar a placa de vídeo."
} else {
    Aviso "Nenhuma placa NVIDIA encontrada: a IA vai rodar no processador (funciona, mas bem mais devagar)."
}

# 4. bibliotecas
Titulo "4/5  Instalando as bibliotecas (a maior parte do download)"
Rodar $uv @("pip", "install", "--python", $py, "--no-deps", "-r", (Join-Path $Pasta "requirements-lock.txt")) "não consegui instalar as bibliotecas"
$indiceUrl = "https://download.pytorch.org/whl/$indice"
& $uv pip install --python $py --no-deps --default-index $indiceUrl @TORCH
if ($LASTEXITCODE -ne 0) {
    Aviso "A versão testada do PyTorch não existe para esta placa; instalando a mais nova compatível."
    Rodar $uv @("pip", "install", "--python", $py, "--no-deps", "--default-index", $indiceUrl, "torch", "torchvision") "não consegui instalar o PyTorch"
}
if ($placa) { $onnx = "onnxruntime-gpu==$ONNX" } else { $onnx = "onnxruntime==$ONNX" }
Rodar $uv @("pip", "install", "--python", $py, "--no-deps", $onnx) "não consegui instalar o ONNX Runtime"
$teste = & $py -c "import torch, fastapi, transformers, faster_whisper, easyocr, onnxruntime, cv2; print('cuda' if torch.cuda.is_available() else 'cpu')"
if ($LASTEXITCODE -ne 0) { Falha "as bibliotecas foram instaladas, mas não abrem" }
$teste = "$($teste | Select-Object -Last 1)".Trim()
if ($placa -and $teste -ne "cuda") {
    Aviso "A placa NVIDIA não respondeu ao PyTorch. Atualize o driver da NVIDIA (nvidia.com/drivers) para a IA usar a placa."
} else {
    Ok "Bibliotecas prontas ($teste)"
}

# 5. modelos de IA (ficam em models\hf, dentro da pasta do programa)
Titulo "5/5  Modelos de IA"
New-Item -ItemType Directory -Force (Join-Path $Pasta "models\hf") | Out-Null
if ($Modelos) {
    & $py -m buscador modelos
} else {
    & $py -c "from buscador import modelos; modelos._rostos()"
    if ($LASTEXITCODE -eq 0) { Ok "Modelo de rostos pronto. Os outros são baixados na primeira vez em que forem usados." }
    else { Aviso "O modelo de rostos não baixou agora. Rode o instalador de novo mais tarde para completar." }
}

# lançador (quem baixou o código do GitHub não tem o BuscadorFAST.exe)
$exe = Join-Path $Pasta "BuscadorFAST.exe"
if (-not (Test-Path $exe)) {
    $csc = Join-Path $env:WINDIR "Microsoft.NET\Framework64\v4.0.30319\csc.exe"
    if (Test-Path $csc) {
        & $csc /nologo /codepage:65001 /target:winexe /optimize+ "/win32icon:$Pasta\launcher\icone.ico" `
            /r:System.Windows.Forms.dll "/out:$exe" "$Pasta\launcher\BuscadorFAST.cs" | Out-Null
    }
}

if ($cacheProprio) { & $uv cache clean 2>$null | Out-Null }   # libera os gigabytes baixados
Write-Host ""
Write-Host "  Tudo pronto!" -ForegroundColor Green
Write-Host ""
if (-not $SemPausa) { Start-Sleep -Seconds 3 }
exit 0
