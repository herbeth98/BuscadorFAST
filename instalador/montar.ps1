<#
  Monta o instalador: dist\BuscadorFAST-Instalador-<versão>.exe
  Precisa do Inno Setup 6 (winget install JRSoftware.InnoSetup) e do ambiente .venv do programa.
  Uso:  instalador\montar.bat [versão]
#>
param([string]$Versao = "1.0.0")
$ErrorActionPreference = "Continue"
$aqui = $PSScriptRoot
$raiz = Split-Path -Parent $aqui
$build = Join-Path $aqui "build"
New-Item -ItemType Directory -Force $build | Out-Null

Write-Host "1/3  Lançador BuscadorFAST.exe"
$csc = Join-Path $env:WINDIR "Microsoft.NET\Framework64\v4.0.30319\csc.exe"
& $csc /nologo /codepage:65001 /target:winexe /optimize+ "/win32icon:$raiz\launcher\icone.ico" `
    /r:System.Windows.Forms.dll "/out:$build\BuscadorFAST.exe" "$raiz\launcher\BuscadorFAST.cs"
if ($LASTEXITCODE -ne 0) { Write-Host "Falhou ao compilar o lançador." -ForegroundColor Red; exit 1 }

Write-Host "2/3  Imagens do assistente"
& (Join-Path $raiz ".venv\Scripts\python.exe") (Join-Path $aqui "imagens.py") $build
if ($LASTEXITCODE -ne 0) { Write-Host "Falhou ao gerar as imagens." -ForegroundColor Red; exit 1 }

Write-Host "3/3  Instalador (Inno Setup)"
$iscc = @("$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe", "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe", "$env:ProgramFiles\Inno Setup 6\ISCC.exe") |
    Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $iscc) { Write-Host "Instale o Inno Setup 6: winget install JRSoftware.InnoSetup" -ForegroundColor Red; exit 1 }
& $iscc /Qp "/DAppVersion=$Versao" (Join-Path $aqui "BuscadorFAST.iss")
if ($LASTEXITCODE -ne 0) { Write-Host "O Inno Setup não conseguiu montar o instalador." -ForegroundColor Red; exit 1 }
$saida = Join-Path $raiz "dist\BuscadorFAST-Instalador-$Versao.exe"
Write-Host ""
Write-Host "Pronto: $saida" -ForegroundColor Green
