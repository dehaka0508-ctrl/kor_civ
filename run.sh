#!/usr/bin/env bash
# macOS / Linux 실행 스크립트: 필요한 부품을 설치하고 게임을 실행한다.
cd "$(dirname "$0")"
PY=python3
command -v python3 >/dev/null 2>&1 || PY=python
$PY -c "import pygame, numpy" >/dev/null 2>&1 || $PY -m pip install --user -r requirements.txt
exec $PY -m korciv "$@"
