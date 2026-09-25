# Demo Plan (3 Minutes)

## 0:00–0:20 Problem
- 1 slide: who suffers, why existing solutions fail (gap table)
- Hook: 1 sentence, relatable

## 0:20–0:40 Solution
- 1 slide: Our AI approach in one line + architecture diagram (from architecture.md)
- Mention: provider-agnostic LLM, optional RAG/ML/Vision activated based on problem

## 0:40–1:50 Live Workflow
- **Live in UI** (frontend/src/pages/Home.jsx):
  1. Enter problem/query
  2. Hit Solve (Agent Workflow) - show loading: Planner → Reasoner → Validator
  3. Show answer + reasoning_steps + sources
  4. If RAG problem: upload PDF via FileUpload -> query with sources
  5. If ML: upload CSV via /api/upload -> train (ml/classifier.py)
- Keep backup video (90 sec) if live fails

## 1:50–2:20 AI Architecture / Innovation
- 1 slide: LangGraph nodes modular, provider switch via env, optional modules
- 1 line: what is novel vs. just API call (RAG + validation + tool node)

## 2:20–2:45 Impact
- Numbers: time saved, users, accuracy if measured (don't fabricate)
- 1 slide: feasibility, cost (Groq free tier)

## 2:45–3:00 Conclusion
- Future scope (2 bullets), team, thank you
- Docs: demo-plan.md, presentation-outline.md

## Rehearsal
- Practice 10 times, 3 min each
- Prepare for: "What is novel?", "How scalable?", "What if LLM fails?" -> answer: mock fallback + retry
