# Hackathon Starter - Demo Commands

.PHONY: demo demo-backend install-backend install-frontend test lint

# Full demo: health, chat, solve (mock + agents), upload
demo:
	@echo "=== Hackathon Starter Demo ==="
	@cd backend && python -m uvicorn app.main:app --port 8000 --host 0.0.0.0 & \
	sleep 3 && \
	echo "--- Health check ---" && \
	curl -s http://localhost:8000/api/health | python -m json.tool && \
	echo "" && \
	echo "--- Chat (mock) ---" && \
	curl -s -X POST http://localhost:8000/api/chat -H "Content-Type: application/json" -d '{"message":"Hello"}' | python -m json.tool && \
	echo "" && \
	echo "--- Solve with agents (mock) ---" && \
	curl -s -X POST http://localhost:8000/api/solve -H "Content-Type: application/json" -d '{"query":"Summarize RAG impact","use_agents":true}' | python -m json.tool && \
	kill %1 2>/dev/null || true && \
	echo "=== Demo complete ==="

# Backend-only demo (assumes server already running on :8000)
demo-backend:
	@echo "=== Backend demo (server must be running on :8000) ==="
	@curl -s http://localhost:8000/api/health | python -m json.tool
	@curl -s -X POST http://localhost:8000/api/chat -H "Content-Type: application/json" -d '{"message":"Hello"}' | python -m json.tool
	@curl -s -X POST http://localhost:8000/api/solve -H "Content-Type: application/json" -d '{"query":"Hello","use_agents":true}' | python -m json.tool

# Install backend dependencies
install-backend:
	@cd backend && python -m pip install -r requirements.txt

# Install frontend dependencies
install-frontend:
	@cd frontend && npm install

# Run all tests
test:
	@cd backend && python -m pytest tests/ -q

# Lint (both)
lint:
	@cd frontend && npm run lint 2>/dev/null || echo "no frontend lint"
	@cd backend && python -m flake8 . 2>/dev/null || echo "no backend lint"
