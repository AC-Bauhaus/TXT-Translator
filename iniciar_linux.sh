#!/usr/bin/env bash
set -e
cd "$(dirname "$0")"
if [ ! -x .venv/bin/python ]; then
  python -m venv .venv
  .venv/bin/python -m pip install -r requirements.txt
fi
exec .venv/bin/python desktop.py
