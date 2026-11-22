# book2md の Windows 環境づくり(PowerShell 5.1 前提)
# 使い方: powershell -NoProfile -ExecutionPolicy Bypass -File setup_windows.ps1 -Device auto
# 入れる先は $HOME\book2md\venv と ~\.paddlex(モデル。初回の推論で自動取得)だけ。
param([ValidateSet('auto','gpu','cpu')][string]$Device = 'auto')
$ErrorActionPreference = 'Stop'
# ネイティブコマンドの失敗は $ErrorActionPreference で止まらないので、毎回 $LASTEXITCODE を見る
function Check($msg) { if ($LASTEXITCODE -ne 0) { throw "$msg (exit $LASTEXITCODE)" } }

$Base = Join-Path $HOME 'book2md'
$Venv = Join-Path $Base 'venv'
$Py = Join-Path $Venv 'Scripts\python.exe'

if (-not (Test-Path $Py)) { uv venv --seed --python 3.11 $Venv; Check 'uv venv' }
& $Py -m pip install --upgrade pip; Check 'pip upgrade'

$gpuOk = $false
if ($Device -ne 'cpu') {
  & $Py -m pip install paddlepaddle-gpu==3.2.2 -i https://www.paddlepaddle.org.cn/packages/stable/cu126/; Check 'paddlepaddle-gpu'
  & $Py -c "import sys, paddle; paddle.utils.run_check(); sys.exit(0 if paddle.device.cuda.device_count() > 0 else 1)"
  if ($LASTEXITCODE -eq 0) { $gpuOk = $true }
  elseif ($Device -eq 'gpu') { throw 'GPU 版 PaddlePaddle の動作確認に失敗しました' }
  else { & $Py -m pip uninstall -y paddlepaddle-gpu; Check 'uninstall gpu' }
}
if (-not $gpuOk) { & $Py -m pip install paddlepaddle==3.2.2 -i https://www.paddlepaddle.org.cn/packages/stable/cpu/; Check 'paddlepaddle cpu' }

& $Py -m pip install paddleocr==3.5.0 pypdfium2==5.7.1 pillow; Check 'paddleocr'
& $Py -c "import paddleocr, pypdfium2, PIL; print('imports ok')"; Check 'import'

if ($gpuOk) { 'BOOK2MD_SETUP device=gpu' } else { 'BOOK2MD_SETUP device=cpu' }
