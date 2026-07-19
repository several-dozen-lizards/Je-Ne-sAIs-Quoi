param([switch]$SkipModel)
$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $PSScriptRoot
$ServiceRoot = Join-Path $Root 'local_services'
$Archive = Join-Path $ServiceRoot 'ComfyUI_windows_portable_nvidia_v0.28.0.7z'
$Portable = Join-Path $ServiceRoot 'ComfyUI_windows_portable'
$ComfyUrl = 'https://github.com/Comfy-Org/ComfyUI/releases/download/v0.28.0/ComfyUI_windows_portable_nvidia.7z'
$ComfySha = '797183fe6165b96a1800793cdc2110e4c62c45e8775647a7166fe8c6290e2fd9'
$ModelName = 'sd_xl_base_1.0.safetensors'
$ModelUrl = 'https://huggingface.co/stabilityai/stable-diffusion-xl-base-1.0/resolve/main/sd_xl_base_1.0.safetensors?download=true'
$ModelSha = '31e35c80fc4829d14f90153f4c74cd59c90b779f6afe05a74cd6120b893f7e5b'
$ModelPath = Join-Path $Portable "ComfyUI\models\checkpoints\$ModelName"

New-Item -ItemType Directory -Force -Path $ServiceRoot | Out-Null
if (-not (Test-Path -LiteralPath $Archive) -or
    (Get-FileHash -Algorithm SHA256 -LiteralPath $Archive).Hash.ToLowerInvariant() -ne $ComfySha) {
  Write-Host 'Downloading official ComfyUI v0.28.0 NVIDIA portable (2.09 GB)...'
  Start-BitsTransfer -Source $ComfyUrl -Destination $Archive -DisplayName 'JNSQ ComfyUI portable'
}
if ((Get-FileHash -Algorithm SHA256 -LiteralPath $Archive).Hash.ToLowerInvariant() -ne $ComfySha) {
  throw 'ComfyUI archive failed its pinned SHA-256 check.'
}
if (-not (Test-Path -LiteralPath (Join-Path $Portable 'ComfyUI\main.py'))) {
  Write-Host 'Extracting the isolated portable runtime...'
  & tar.exe -xf $Archive -C $ServiceRoot
  if ($LASTEXITCODE -ne 0) { throw 'Windows tar could not extract the official 7z archive.' }
}
if (-not $SkipModel) {
  New-Item -ItemType Directory -Force -Path (Split-Path -Parent $ModelPath) | Out-Null
  if (-not (Test-Path -LiteralPath $ModelPath) -or
      (Get-FileHash -Algorithm SHA256 -LiteralPath $ModelPath).Hash.ToLowerInvariant() -ne $ModelSha) {
    Write-Host 'Downloading Stability AI SDXL Base 1.0 (6.94 GB)...'
    Start-BitsTransfer -Source $ModelUrl -Destination $ModelPath -DisplayName 'JNSQ SDXL Base 1.0'
  }
  if ((Get-FileHash -Algorithm SHA256 -LiteralPath $ModelPath).Hash.ToLowerInvariant() -ne $ModelSha) {
    throw 'SDXL checkpoint failed its pinned SHA-256 check.'
  }
}
$Manifest = [ordered]@{
  format = 1
  installed_at = (Get-Date).ToString('o')
  comfyui = [ordered]@{ version = 'v0.28.0'; sha256 = $ComfySha; source = $ComfyUrl }
  checkpoint = [ordered]@{ name = $ModelName; sha256 = $ModelSha; source = $ModelUrl; license = 'CreativeML Open RAIL++-M' }
  policy = @('loopback only', 'API nodes disabled', 'no custom nodes', 'no cloud fallback')
}
$Manifest | ConvertTo-Json -Depth 5 | Set-Content -Encoding UTF8 -LiteralPath (Join-Path $ServiceRoot 'atelier_gpu_manifest.json')
Write-Host 'Atelier GPU runtime installed and verified.'
