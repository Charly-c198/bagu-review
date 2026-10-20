#!/usr/bin/env bash
# 本地一键检查（与 CI 同口径）；Git Bash / WSL / Linux 均可。
#   ./scripts/check.sh            后端 ruff + pytest，前端类型检查 + 构建
#   ./scripts/check.sh --with-e2e 额外跑本机 Edge 冒烟
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
if [[ -x "$root/../.venv/Scripts/python.exe" ]]; then
  py="$root/../.venv/Scripts/python.exe"
elif [[ -x "$root/../.venv/bin/python" ]]; then
  py="$root/../.venv/bin/python"
else
  py="${PYTHON:-python3}"
fi

cd "$root/backend"
if "$py" -m ruff --version >/dev/null 2>&1; then
  "$py" -m ruff check app tests
else
  echo "WARN: 未安装 ruff，跳过 lint（pip install -r backend/requirements-dev.txt）"
fi
"$py" -m pytest -q

cd "$root/frontend"
npm run build
if [[ "${1:-}" == "--with-e2e" ]]; then
  npm run e2e
fi

echo "全部检查通过"
