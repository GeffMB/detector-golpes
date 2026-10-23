# Baixa a versão mais recente do GitHub e substitui os arquivos desta pasta.
# A pasta .venv (bibliotecas instaladas) é mantida.
#
# Uso, dentro da pasta do projeto:
#   powershell -ExecutionPolicy Bypass -File atualizar.ps1

$ErrorActionPreference = "Stop"
$destino = Split-Path -Parent $MyInvocation.MyCommand.Path
$zip = Join-Path $env:TEMP "detector-golpes.zip"
$tmp = Join-Path $env:TEMP "detector-golpes-atualizacao"

Write-Host "Baixando a versão mais recente..."
Invoke-WebRequest "https://github.com/GeffMB/detector-golpes/archive/refs/heads/main.zip" -OutFile $zip

if (Test-Path $tmp) { Remove-Item $tmp -Recurse -Force }
Expand-Archive $zip -DestinationPath $tmp
Copy-Item (Join-Path $tmp "detector-golpes-main\*") $destino -Recurse -Force

Remove-Item $zip, $tmp -Recurse -Force
Write-Host "Pronto: detector atualizado." -ForegroundColor Green
