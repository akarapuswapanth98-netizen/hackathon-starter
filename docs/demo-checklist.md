# Pre-Demo Checklist (2 min before judges)

- [ ] Backend running: `cd backend && python -m uvicorn app.main:app --reload` -> http://localhost:8000/docs shows 200
- [ ] Frontend running: `cd frontend && npm run dev` -> http://localhost:5173 loads, header shows Backend OK
- [ ] `.env` set: `backend/.env` has `LLM_PROVIDER=mock` (or real key if you have), `RAG_ENABLED=false` unless RAG demo
- [ ] Samples ready: dropdown in Home works, `examples/sample-inputs/*.json` copied to clipboard
- [ ] File upload test: drop a small.txt -> shows saved_as in UI
- [ ] Solve test: query "Explain AI" -> get answer + steps + mock banner (if mock)
- [ ] Error test: empty query -> ErrorBanner appears, Retry works
- [ ] Backup video: 90 sec screen record of successful Solve (if live fails, play video)
- [ ] Screenshots: `docs/screenshots/` has health/empty/loading/success/sources
- [ ] Presentation: `docs/presentation-outline.md` filled with today's problem, architecture diagram ready
- [ ] `git status` clean, no secrets committed
- [ ] Second laptop / hotspot ready if venue WiFi fails

If any fails: check `VITE_API_URL` in `frontend/.env`, `CORS_ORIGINS` in `backend/.env`, `python -m pytest tests/ -v` 16 passed.
