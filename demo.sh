#!/usr/bin/bash
# hackathon-starter - Unix/Linux demo script
# Runs a complete FoodBridge match cycle with demo reset
# Usage: ./demo.sh from the repository root

set -e

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT_DIR"

BLUE='\033[0;34m'
YELLOW='\033[1;33m'
GREEN='\033[0;32m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

echo -e "${BLUE}=== Hackathon Starter Demo ===${NC}"
echo ""

# Backend setup and start
echo -e "${YELLOW}1. Starting backend server...${NC}"
cd backend

# Create venv if it doesn't exist
if [ ! -d "venv" ]; then
    python3 -m venv venv
fi

# Activate venv and install deps
source venv/bin/activate
pip install -r requirements.txt > /dev/null 2>&1

echo "   Starting uvicorn server on port 8000..."

# Start backend in background
uvicorn app.main:app --port 8000 --host 0.0.0.0 &
BACKEND_PID=$!

# Wait for server to start
sleep 5

echo -e "${GREEN}Backend server started${NC}"
echo ""

# Test basic endpoints
echo -e "${YELLOW}2. Testing API endpoints...${NC}"

# Health check
echo -n "   GET /api/health... "
health=$(curl -s http://localhost:8000/api/health)
echo -e " - Status: $(echo $health | python3 -c "import sys,json; print(json.load(sys.stdin)['status'])" )" -foreground

# List restaurants
echo -n "   GET /api/foodbridge/restaurants... "
rests=$(curl -s http://localhost:8000/api/foodbridge/restaurants)
count=$(echo $rests | python3 -c "import sys,json; print(len(json.load(sys.stdin)['restaurants']))")
echo -e " - Found $count restaurant(s)" -foreground

# List surplus (available by default)
echo -n "   GET /api/foodbridge/surplus... "
surplus=$(curl -s http://localhost:8000/api/foodbridge/surplus)
count=$(echo $surplus | python3 -c "import sys,json; print(len(json.load(sys.stdin)['surplus']))")
echo -e " - Found $count surplus lot(s)" -foreground

# Run a match
echo -n "   POST /api/foodbridge/match... "
match=$(curl -s -X POST http://localhost:8000/api/foodbridge/match -d '{"surplus_id": "food-001"}' -H "Content-Type: application/json")
success=$(echo $match | python3 -c "import sys,json; print(json.load(sys.stdin)['success'])" 2>/dev/null || echo "unknown")
echo -e " - Success: $success" -foreground
workflow_id=$(echo $match | python3 -c "import sys,json; print(json.load(sys.stdin).get('workflow_id','N/A'))" 2>/dev/null || echo "N/A")
echo -e "   Workflow ID: $workflow_id" -foreground

# Demo reset
echo ""
echo -e "${YELLOW}3. Running demo reset...${NC}"
reset=$(curl -s -X POST http://localhost:8000/api/foodbridge/demo/reset)
echo -e " - Success: $(echo $reset | python3 -c "import sys,json; print(json.load(sys.stdin)['success'])" 2>/dev/null || echo "unknown") - $(echo $reset | python3 -c "import sys,json; print(json.load(sys.stdin)['message'])" 2>/dev/null || echo "unknown")" -foreground

# Run another match after reset
echo ""
echo -e "${YELLOW}4. Running match after reset...${NC}"
match2=$(curl -s -X POST http://localhost:8000/api/foodbridge/match -d '{"surplus_id": "food-001"}' -H "Content-Type: application/json")
success2=$(echo $match2 | python3 -c "import sys,json; print(json.load(sys.stdin)['success'])" 2>/dev/null || echo "unknown")
echo -e " - Success: $success2" -foreground
total2=$(echo $match2 | python3 -c "import sys,json; print(json.load(sys.stdin).get('total_allocated',0))" 2>/dev/null || echo "0")
echo -e "   Total allocated: $total2 meals" -foreground

# Cleanup
echo ""
echo -e "${YELLOW}5. Stopping backend...${NC}"
kill $BACKEND_PID 2>/dev/null || true
wait $BACKEND_PID 2>/dev/null || true
echo -e "${GREEN}Done!${NC}"