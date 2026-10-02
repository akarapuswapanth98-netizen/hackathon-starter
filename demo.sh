#!/usr/bin/env bash
# hackathon-starter - Unix demo script (generic chat/solve flow)
# Usage: ./demo.sh from the repository root
set -e
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT_DIR"

echo "=== Hackathon Starter Demo ==="
cd backend
if [ ! -d "venv" ]; then python3 -m venv venv; fi
# shellcheck disable=SC1091
source venv/bin/activate
pip install -r requirements.txt > /dev/null 2>&1
uvicorn app.main:app --port 8000 --host 0.0.0.0 &
BACKEND_PID=$!
sleep 5
echo "GET /api/health..."
curl -s http://localhost:8000/api/health | python3 -m json.tool
echo "POST /api/chat..."
curl -s -X POST http://localhost:8000/api/chat -H "Content-Type: application/json" -d '{"message":"Hello"}' | python3 -m json.tool
echo "POST /api/solve (agents)..."
curl -s -X POST http://localhost:8000/api/solve -H "Content-Type: application/json" -d '{"query":"Summarize RAG impact","use_agents":true}' | python3 -m json.tool
kill $BACKEND_PID 2>/dev/null || true
wait $BACKEND_PID 2>/dev/null || true
echo "Done!"
