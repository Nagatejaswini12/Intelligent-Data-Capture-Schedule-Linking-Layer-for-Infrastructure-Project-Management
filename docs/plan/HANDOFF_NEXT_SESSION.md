# Hand-off prompt for the next Claude Code session

Paste everything below the line into the new session, opened in this repository folder.

---

You are continuing work on **P2E Bridge** (SIH26122, Oil India Limited): FastAPI + SQLAlchemy backend (`p2e/`), React 19 + TypeScript + Vite frontend (`web/`), tests in `tests/` (pytest) and `web/src/**/*.test.ts(x)` (vitest). Repo: https://github.com/Nagatejaswini12/Intelligent-Data-Capture-Schedule-Linking-Layer-for-Infrastructure-Project-Management, working branch `lohith/development`; finished work is pushed to `main` too (fetch first, fast-forward only). Read `README.md`, `PRODUCT.md`, `docs/OFFICIAL_RESOURCES.md` first. Use only official sources (BHASHINI, AIKosh, data.gov.in, API Setu, oil-india.com). Never commit real API keys; demo keys live only in `start_demo.bat` and are labelled demo.

## State when the previous session stopped (UNCOMMITTED in the working tree — review with `git status` / `git diff`)

Done and verified (frontend: 17 vitest tests pass, `npm run build` passes; backend: test_llm, test_official, test_phase4 pass; the FULL pytest suite has NOT been re-run after these changes):

1. **AI client** `p2e/llm.py`: stdlib OpenAI-compatible chat client (`ChatModel.chat`, `.invoke`), guard rails: per-minute/per-day call budget, output-token cap, timeout, remote endpoints refused unless `P2E_LLM_ALLOW_REMOTE=1`, key only from `P2E_LLM_API_KEY`. Wired through `p2e/link/adjudicate.from_env()` when `P2E_LLM_MODEL` is set. Bulk linker tie-breaker now opt-in (`app.state.tiebreak`, env `P2E_LLM_TIEBREAKER=1`).
2. **Assistant** `p2e/assistant.py`: deterministic answer first; optional model rewrites it in the user's language (en/ta/hi) from `<facts>` only. Guard rails: strict scope system prompt with `OUT_OF_SCOPE` sentinel, every number in the answer must appear in the facts (else fall back to rules), whole official company sheet given as facts. Response has `answered_by`. Route passes `llm=request.app.state.llm`.
3. **Time Agent** `p2e/agent/time_agent.py`: rules first, model only when rules leave a required field missing.
4. **Frontend i18n sweep**: nearly every page string moved to `web/src/i18n.ts` keys (en/ta/hi) via `T()`; `humanize()` in `web/src/utils/format.ts` now translates data values (statuses, disciplines, decisions) through the `V` dictionary; `setCurrentLang` is set in `App` render. Memory page example questions intentionally stay English (English query templates).
5. **Voice/chat fixes**: voice language follows the page language; spoken questions are sent immediately and answered aloud; picks an installed browser voice and shows a notice when the device has no Tamil/Hindi voice; "Thinking…" bubble; AI badge.
6. **Light theme only**: dark toggle removed, old saved dark preference cleared (this also fixed the white logo box).
7. **Landing page** `web/src/pages/Public.tsx` + `web/src/styles/public.css`: Apple-style scroll film (242 WebP frames in `web/public/seq/` drawn on a canvas, scrubbed by GSAP ScrollTrigger, Lenis smooth scroll), word-by-word statement reveal, 3D tilting dashboard mock with Kanban, horizontally pinned agent cards, counters. `lenis` added to `web/package.json`.
8. `tests/test_llm.py` (guard rails), `start_demo.bat` sets a local model endpoint (to be replaced, see below).

First steps: run `.venv\Scripts\python -m pytest -q` (≈9 min) and `cd web; npm test; npm run build`; fix failures; commit on `lohith/development`; push to `main` only when green.

## New requirements from the owner (do these next)

### A. No Ollama. Run the model with ONNX, downloaded from Hugging Face, on the GPU
- Remove the dependency on Ollama (`start_demo.bat` currently points at `http://localhost:11434/v1`).
- Use an ONNX build of a small instruct model from Hugging Face (official ONNX exports, e.g. the `onnx-community/*` or `microsoft/*-onnx` repos of Qwen2.5 / Qwen3 / Phi in the 0.5B–4B range, int4/q4f16). Pick one that answers well in Tamil and Hindi; verify the licence allows commercial use.
- Inference must run on the GPU through ONNX Runtime and must not depend on any external account or service.
- Keep every guard rail from `p2e/llm.py` / `assistant.ai_answer` (scope sentinel, facts-only, number check, budgets, deterministic fallback). The model only rephrases verified facts; it never decides links or writes the schedule.

### B. Deploy everything on Vercel: frontend, backend, database
- Frontend: Vite static build.
- Backend: FastAPI on Vercel's Python runtime (serverless functions). Adapt: read-only filesystem except `/tmp`; move uploads to **Vercel Blob**; the SSE live stream (`useStream`) must degrade to polling if long-lived connections are cut; respect the function bundle size limit.
- Database: replace SQLite with **Postgres created from the Vercel dashboard (Vercel Marketplace, e.g. Neon)**; `P2E_DB_URL` from Vercel env vars; add a migration/seed step for the synthetic project (`scripts/phase1/init_database.py`). Keep SQLite for local dev and tests.
- Secrets only in Vercel environment variables; nothing in the repo.

### C. IMPORTANT constraint to resolve before coding A + B
**Vercel has no GPUs, and its serverless functions cannot hold a multi-GB model.** So "ONNX on GPU" cannot run inside the Vercel backend. Recommended design that keeps everything on Vercel and independent of third parties:
- **Run the ONNX model in the user's browser on their GPU via WebGPU** (`@huggingface/transformers` v3 with `device: "webgpu"`, or `onnxruntime-web`), model files served from Hugging Face or Vercel Blob and cached by the browser. The backend endpoint returns the verified facts and the deterministic answer; the browser model rewrites them in the chosen language; the same guard rails (scope sentinel, number check against the facts) run in the browser before showing the answer; fall back to the deterministic answer when WebGPU is unavailable or the model is still downloading (show progress).
- Use a model small enough to download and run on an ordinary laptop GPU (≈0.5B–1.5B q4); test the download size and first-answer latency.
- Alternative if a server-side model is required: a separate GPU machine running `onnxruntime-genai` (CUDA/DirectML) behind the existing OpenAI-compatible client in `p2e/llm.py`. That machine is NOT on Vercel; say so to the owner.
Explain the trade-off to the owner in one paragraph and get a yes before building.

### D. Remaining earlier items
- Re-check the language switch on every page in the browser (en/ta/hi) and fix any string still in English.
- Verify the landing scroll film, sign-in "Fill demo credentials", request-access flow, and the assistant/Time Agent in Tamil and Hindi in a real browser (desktop + mobile width).
- Admin screen to review access requests (`GET /api/v1/access-requests` exists, no UI yet).
- Richer dashboards (charts, Kanban) inside the app.
- Update README (architecture, deployment on Vercel, AI design and guard rails, test counts) and push to `main`.

Security note for the owner: a Groq API key was pasted into the previous chat. It was never written to the repository, but it should be revoked and rotated in the Groq console.
