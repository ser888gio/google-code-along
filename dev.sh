#!/bin/bash

set -e

echo " Ensuring frontend and backend dependencies are installed..."

# Install frontend dependencies
(cd frontend && npm install)

# Install backend dependencies
(
  cd backend
  if [ ! -d ".venv" ] || [ ! -f ".venv/bin/activate" ]; then
    echo "🐍 Creating Python virtual environment..."
    sudo apt update && sudo apt install -y python3-venv
    # Check for python3 and the venv module. The 'ensurepip' error indicates python3-venv is missing.
    if ! python3 -c "import venv" &>/dev/null; then
      echo "❌ Error: The 'python3-venv' package is not installed." >&2
      echo "Please install it by running the following command, then re-run this script:" >&2
      echo "sudo apt update && sudo apt install -y python3-venv" >&2
      exit 1
    fi
    python3 -m venv .venv
  fi
  source .venv/bin/activate
  pip install --upgrade pip
  pip install -r requirements.txt --break-system-packages
)

echo "🚀 Starting Backend..."
(cd backend && source .venv/bin/activate && uvicorn main:app --reload) &

echo "🚀 Starting Frontend..."
(cd frontend && npm run dev) &

echo "✅ Both servers are starting. Press Ctrl+C to stop them."
wait
