#!/usr/bin/env bash
# install.sh —— 把本包内的 7 个 skill 安装到 WorkBuddy / Claude Code 的 skills 目录
# 用法：
#   bash _shared/install.sh                       # 默认链接到 ~/.workbuddy/skills
#   bash _shared/install.sh --copy                # 复制而非建链接
#   bash _shared/install.sh --target /path/skills # 指定目标目录
set -euo pipefail

TARGET="$HOME/.workbuddy/skills"
COPY=0
while [ $# -gt 0 ]; do
  case "$1" in
    --copy) COPY=1; shift ;;
    --target) TARGET="$2"; shift 2 ;;
    *) echo "未知参数：$1" >&2; exit 2 ;;
  esac
done

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SKILLS="business-lecture-orchestrator courseware-notes lecture-notes-zh rigorous-derivation exam-problems investment-lecture-orchestrator platform-economy-orchestrator"

echo "== 安装讲义 skill 包 =="
echo "包根目录：$ROOT"
echo "目标目录：$TARGET"
echo

mkdir -p "$TARGET"
for s in $SKILLS; do
  src="$ROOT/$s"; dst="$TARGET/$s"
  [ -d "$src" ] || { echo "  缺少 $s，跳过"; continue; }
  rm -rf "$dst"
  if [ "$COPY" = "1" ]; then
    cp -R "$src" "$dst"; echo "  [复制] $s"
  else
    ln -s "$src" "$dst"; echo "  [链接] $s"
  fi
done

echo
echo "== 环境自检 =="
python3 "$ROOT/_shared/doctor.py" || python "$ROOT/_shared/doctor.py"
echo
echo "安装完成。若自检有缺失项，请按其提示补齐后再开工。"
