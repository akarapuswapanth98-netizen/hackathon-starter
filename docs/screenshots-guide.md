# Screenshots & Demo Capture Guide

## What to capture (before and during demo)

1. **Health check** - Frontend header shows Backend OK + provider/model
   - Command: Run `python -m uvicorn app.main:app --reload` + `npm run dev`, click Health, screenshot badge bar.

2. **Empty state** - `Home` with sample selector and empty result card (💡)
   - Shows clean input UX, easy for judges.

3. **Loading** - Click Solve, capture `⏳ AI thinking...` with steps bar

4. **Success (mock)** - Mock answer with Demo Mode yellow banner + reasoning_steps + metadata JSON
   - Use `examples/sample-inputs/sample-solve.json` -> Solve

5. **Sources panel** - With RAG: upload `examples/sample-inputs/rag.json` style PDF -> Solve with RAG ON -> Sources cards.

6. **Error banner** - Submit empty query -> red Error banner with Retry/Dismiss + missing key hint.

7. **File upload** - Drag & drop zone highlighted.

## How to capture

- Browser: Chrome, 1280x800, no bookmarks bar
- Use `Win + Shift + S` or Chrome DevTools screenshot (Cmd+Shift+P > Capture)
- Save to `docs/screenshots/` (create folder) as `01-health.png`, `02-empty.png`, etc.

## Tips

- Mock mode is demo-safe: yellow banner clarifies, wiring is real.
- Always show `reasoning_steps` collapsed - proves LangGraph.
- Keep `VITE_API_URL=http://localhost:8000` visible in `.env.example` for judges.
