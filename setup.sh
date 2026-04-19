#!/usr/bin/env bash
# lambda-ocr setup script
# Apple Silicon macOS 向け: PaddleOCR をセットアップする専用venvを作成
#
# Usage:
#   ./setup.sh               # ./.venv_paddleocr に venv を作成
#   PREFIX=/path ./setup.sh  # カスタムパスに venv を作成

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="${PREFIX:-$SCRIPT_DIR/.venv_paddleocr}"

# Python 3.13 を優先(3.11のPPAにcertifi問題があるため)
PY=""
for cand in /opt/homebrew/Cellar/python@3.13/*/bin/python3 /opt/homebrew/bin/python3.13 /opt/homebrew/bin/python3; do
  if [ -x "$cand" ]; then PY="$cand"; break; fi
done

if [ -z "$PY" ]; then
  echo "ERROR: Python 3.13 が見つかりません。 brew install python@3.13 を実行してください。" >&2
  exit 1
fi

echo "[setup] Python: $PY"
echo "[setup] venv: $VENV_DIR"

"$PY" -m venv "$VENV_DIR"
"$VENV_DIR/bin/python" -m pip install --upgrade pip --quiet

echo "[setup] paddlepaddle インストール中..."
"$VENV_DIR/bin/pip" install paddlepaddle==3.2.1 \
  -i https://www.paddlepaddle.org.cn/packages/stable/cpu/

echo "[setup] paddleocr インストール中..."
"$VENV_DIR/bin/pip" install -U "paddleocr[doc-parser]"

echo "[setup] 追加依存 インストール中..."
"$VENV_DIR/bin/pip" install -U pillow pyyaml openpyxl

echo
echo "[setup] 完了"
echo "  activate: source $VENV_DIR/bin/activate"
echo "  python:   $VENV_DIR/bin/python"
