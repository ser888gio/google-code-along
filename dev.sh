#!/bin/bash
# To start should be run from the root project. Command: bash dev.sh

echo "Starting Backend..."
(cd backend && source .venv/Scripts/activate && uvicorn main:app --reload) &

echo "Starting Frontend..."
(cd frontend && npm run dev) &

echo "Both servers are starting. Press Ctrl+C to stop them."
wait
