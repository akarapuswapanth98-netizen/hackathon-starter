# Hackathon Starter - Demo Commands
# Usage: make demo  (or: make demo-backend, make demo-full)

.PHONY: demo demo-backend demo-full install-backend install-frontend test lint

# Full demo: start backend, run match, reset, run match again, show endpoints
demo: install-backend
	@echo "=== Starting FoodBridge demo ==="
	@cd backend && python -m uvicorn app.main:app --port 8000 --host 0.0.0.0 & \
	sleep 3 && \
	echo "--- Health check ---" && \
	curl -s http://localhost:8000/api/health | python -m json.tool && \
	echo "" && \
	echo "--- Restaurants ---" && \
	curl -s http://localhost:8000/api/foodbridge/restaurants | python -m json.tool && \
	echo "" && \
	echo "--- First match (consumes lot) ---" && \
	curl -s -X POST http://localhost:8000/api/foodbridge/match \
	  -H "Content-Type: application/json" \
	  -d '{"surplus_id":"food-001"}' | python -m json.tool && \
	echo "" && \
	echo "--- Second match (409 - lot consumed) ---" && \
	curl -s -X POST http://localhost:8000/api/foodbridge/match \
	  -H "Content-Type: application/json" \
	  -d '{"surplus_id":"food-001"}' | python -m json.tool && \
	echo "" && \
	echo "--- Demo reset ---" && \
	curl -s -X POST http://localhost:8000/api/foodbridge/demo/reset | python -m json.tool && \
	echo "" && \
	echo "--- Surplus after reset (available again) ---" && \
	curl -s http://localhost:8000/api/foodbridge/surplus | python -m json.tool && \
	echo "" && \
	echo "--- Match again after reset ---" && \
	curl -s -X POST http://localhost:8000/api/foodbridge/match \
	  -H "Content-Type: application/json" \
	  -d '{"surplus_id":"food-001"}' | python -m json.tool && \
	kill %1 2>/dev/null || true && \
	echo "=== Demo complete ==="

# Backend-only demo (assumes server already running on :8000)
demo-backend:
	@echo "=== Backend demo (server must be running on :8000) ==="
	@curl -s http://localhost:8000/api/health | python -m json.tool
	@curl -s http://localhost:8000/api/foodbridge/restaurants | python -m json.tool
	@curl -s -X POST http://localhost:8000/api/foodbridge/match -H "Content-Type: application/json" -d '{"surplus_id":"food-001"}' | python -m json.tool
	@curl -s -X POST http://localhost:8000/api/foodbridge/match -H "Content-Type: application/json" -d '{"surplus_id":"food-001"}' | python -m json.tool
	@curl -s -X POST http://localhost:8000/api/foodbridge/demo/reset | python -m json.tool
	@curl -s http://localhost:8000/api/foodbridge/surplus | python -m json.tool
	@curl -s -X POST http://localhost:8000/api/foodbridge/match -H "Content-Type: application/json" -d '{"surplus_id":"food-001"}' | python -m json.tool

# Install backend dependencies
install-backend:
	@cd backend && python -m venv venv && . venv/bin/activate && pip install -r requirements.txt

# Install frontend dependencies
install-frontend:
	@cd frontend && npm install

# Run all tests
test:
	@cd backend && . venv/bin/activate && pytest tests/ -q

# Lint (both)
lint:
	@cd frontend && npm run lint 2>/dev/null || echo "no frontend lint"
	@cd backend && . venv/bin/activate && python -m flake8 . 2>/dev/null || echo "no backend lint"