#!/usr/bin/env bash
# Starts Worky and opens it in your browser. Run this any time you
# want to use the app; no need to open VS Code.
set -e
cd "$(dirname "$0")"

if [ ! -d "venv" ]; then
  echo "First run detected. Running setup.sh first..."
  ./setup.sh
fi

source venv/bin/activate
python -m server.app
