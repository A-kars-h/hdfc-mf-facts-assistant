# HDFC Mutual Fund Facts Assistant

A retrieval-augmented assistant that answers **facts-only** questions about a closed
corpus of five HDFC Direct Growth mutual fund pages. It cites every answer back to
the page it came from, refuses advice-seeking questions, and never invents a URL.

> **Facts-only. No investment advice.**

---

## 1. Scope

| | |
|---|---|
| **AMC** | HDFC Asset Management |
| **Corpus** | 5 pages, all Direct Growth |
| **Schemes** | Large Cap · Equity (Flexi Cap) · ELSS Tax Saver · Small Cap · Balanced Advantage |
| **Language** | **English only** — `all-MiniLM-L6-v2` is an English model |
| **Advice** | Never given. Opinion questions are refused (Refusal A). |
| **Performance claims** | Never emitted. Return-shaped figures are screened on the output. |
| **Out of corpus** | Refused (Refusal B), with the boundary stated once |

The full source list with per-page fetch timestamps: `artifacts/source_list.md` / `.csv`.

---

## 2. Setup

### 2.1 Prerequisites

- **Python 3.10+** (built and tested on 3.10.7). 3.11+ is fine; `tomllib` is not used.
- ~2.5 GB of disk for the CPU torch wheel and the embedding model.

### 2.2 Install

Install the **CPU** torch wheel *before* `requirements.txt`. Otherwise pip pulls
~2.5 GB of CUDA wheels that then conflict with chromadb's `onnxruntime`:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install torch==2.14.0 --index-url https://download.pytorch.org/whl/cpu
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

`numpy` is pinned to `1.25.2` because `chromadb==1.5.9` is not numpy-2.x compatible.

> **`make` is optional.** A `Makefile` is provided, but `make` was **not installed**
> on the build machine (Windows, no GNU make, no git-bash make). Every command
> below is the raw command the Makefile runs, so nothing depends on `make` being
> present. NFR-11's "≤3 commands" is satisfied by the copy-paste blocks in §2.4.

### 2.3 Configure

```powershell
Copy-Item .env.example .env
```

`.env.example` ships with no real values. Nothing in `.env` is ever committed
(`.gitignore` lists it), and no API key exists anywhere in the source.

| Variable | Required | Notes |
|---|---|---|
| `LLM_PROVIDER` | yes, for answers | `openai` or `ollama`. `none` disables generation. |
| `LLM_MODEL` | yes, for answers | e.g. `qwen/qwen3.8-27b` |
| `LLM_API_KEY` | for `openai` | Env only. Missing key → readable message, never a traceback. |
| `EMBEDDING_MODEL` | no | Defaults to `sentence-transformers/all-MiniLM-L6-v2`. Do not substitute. |
| `SIMILARITY_THRESHOLD` | **no** | Leave unset. It is derived, not typed. See §2.5. |

### 2.4 Run — three commands

```powershell
# 1. fetch the 5 corpus pages -> data/raw/*.html, *.txt
python scripts/spike_fetch.py

# 2. chunk, embed, build Chroma + BM25 + manifest -> data/, artifacts/manifest.json
python -m src.ragbot.ingest

# 3. launch the UI on 127.0.0.1:8501
python -m streamlit run src/ragbot/ui/app.py
```

Step 2 is idempotent: re-running reports `pages embedded: 0, pages skipped: 5` and
makes **zero** embed calls. Use `--reindex` to force a rebuild.

Other entry points:

```powershell
python -m src.ragbot.retrieval "What is the minimum SIP for HDFC ELSS?"   # CLI: intent, candidates, gate
python -m src.ragbot.eval            # the 8-query sample set, M-1..M-7
python -m src.ragbot.eval.calibrate  # derive the threshold, write artifacts/calibration.json
python -m pytest tests -q            # 689 tests
```

### 2.5 The threshold is derived, never typed

`SIMILARITY_THRESHOLD` has **no default**. Until calibration has run,
`Settings.require_similarity_threshold()` raises `NotCalibratedError`, so an
un-calibrated deployment fails *at the gate* rather than silently never answering.
The sanctioned value comes from `artifacts/calibration.json`
(`require_similarity_threshold()` reads it as a fallback) and is **0.7562**,
derived from the sweep curve in `artifacts/eval_report.md`.

To recalibrate after a corpus or model change:

```powershell
python -m src.ragbot.eval.calibrate
```

---

## 3. Architecture summary

```
question
  │
  ├─► safety/pii.py        scan (PAN, Aadhaar+Verhoeff, account, OTP, email, phone)
  │                       → Refusal C if found. Runs BEFORE embed, LLM and logs.
  ├─► retrieval/intent.py  rules-first: factual | opinion | out_of_scope | corpus_sources
  │     ├─ opinion        → Refusal A (no retrieval, no model)
  │     ├─ out_of_scope   → Refusal B (no retrieval, no model)
  │     └─ factual        ▼
  ├─► retrieval/          dense (Chroma, raw cosine) + sparse (BM25)
  │                       → RRF fusion (k=60, rank only)
  │                       → gate on **raw dense similarity**, never a fused score
  │     ├─ below / closed → Refusal B (no model)
  │     └─ open           ▼
  ├─► generation/         prompt → stream → **validate on the output**
  │                       sentence cap · one in-corpus citation from provenance ·
  │                       per-page last_updated · advice screen · return-shape screen ·
  │                       grounding
  └─► Answer              rendered by ui/app.py — presentation only
```

Module map:

| Package | Responsibility |
|---|---|
| `core/` | `config` (settings), `models` (Pydantic contracts), `errors`, `logging` (with `redact()`) |
| `ingest/` | `fetch` · `clean` · `chunker` · `embedder` · `writer` |
| `retrieval/` | `intent` · `dense` · `sparse` · `fusion` · `gate` |
| `generation/` | `prompts` · `llm` (single egress point) · `validate` · `educational` · `corpus` · `pipeline` |
| `safety/` | `pii` |
| `ui/` | `app.py` — Streamlit, no logic |
| `eval/` | `runner` · `checks` · `judge` · `calibrate` · `dataset` |

Two invariants are enforced **by the type system** rather than by convention:

1. `RetrievedChunk` has `dense_score` (raw cosine) and `fused_rank` (ordering) as
   **separate fields, and deliberately no `score` field**. A test asserts
   `not hasattr(rc, "score")`. RRF scores are scale-free and cannot be thresholded.
2. `_route()` / `_generate()` take a `PIIResult` and raise `UnscannedInputError`
   unless it is the product of a real, enforced scan. The guard **raises** rather
   than asserts, because `python -O` strips asserts.

---

## 4. Deliverables

| # | Deliverable | Where | Status |
|---|---|---|---|
| D-1 | ≤3-min demo video | `artifacts/demo_script.md` | ✅ [Demo video on Google Drive](https://drive.google.com/file/d/1wG_o83w-RLmd-N0AX-HHjm1Bt15drxhJ/view?usp=sharing) — **2m 42.6s, verified from the file's `mvhd` atom** |
| D-2 | Source list, CSV **and** MD | `artifacts/source_list.csv`, `artifacts/source_list.md` | ✅ generated by `scripts/phase8_source_list.py` |
| D-3 | This README | `README.md` | ✅ |
| D-4 | Sample Q&A, 8 queries, generated from the eval run | `artifacts/sample_qa.md` | ✅ generated by `scripts/phase8_sample_qa.py` from `artifacts/eval_run_capture.json` |
| D-5 | Disclaimer snippet | `artifacts/disclaimer_snippet.md` | ✅ quotes the `DISCLAIMER` constant verbatim |
| — | Eval report + calibration curve | `artifacts/eval_report.md`, `artifacts/calibration.json` | ✅ |
| — | PRD §18 acceptance checklist | `artifacts/prd_checklist.md` | ✅ 27 ✅ · 2 ⚠️ · 0 ❌ |
| — | UI captures | `artifacts/screenshots/` | ⚠️ **text renders, not images** — no browser on this machine |

Regenerate every generated artefact with `make deliverables` (or run the four
`scripts/phase8_*.py` in order: `source_list` → `eval_capture` → `sample_qa` →
`screenshots`).

---

## 5. Demo

**Recording:** [HDFC MF facts assistant - Demo video.mp4](https://drive.google.com/file/d/1wG_o83w-RLmd-N0AX-HHjm1Bt15drxhJ/view?usp=sharing)
(Google Drive, "anyone with the link"). **Duration 2m 42.6s, read from the file's
own `mvhd` atom** — verified, not assumed:

```powershell
python scripts/verify_demo_duration.py 1wG_o83w-RLmd-N0AX-HHjm1Bt15drxhJ
```

The beat sheet it follows is `artifacts/demo_script.md`. The run was rehearsed
twice before recording (author-attested — the duration above is machine-verified,
the rehearsal count is not, since rehearsal leaves no artefact). To run the app
yourself, it binds to `127.0.0.1` only — see §6.

---

## 6. Deployment

`.streamlit/config.toml` sets `server.address = "127.0.0.1"` explicitly, so the
bind is correct **even when `streamlit run` is invoked without flags**:

```toml
[server]
address = "127.0.0.1"
port = 8501
headless = true
fileWatcherType = "none"

[browser]
gatherUsageStats = false
```

- **Single process, loopback only, no auth, no persistence across restarts.**
  No session state leaves the process.
- `fileWatcherType = "none"` is deliberate, not a default: Streamlit's watcher
  resolves the path of every module in `sys.modules`, which here means all of
  `transformers` (~200 vision/audio submodules) pulled in by
  sentence-transformers, each failing on missing `torchvision`. Measured cost of
  leaving it on: 1,943 lines and 102 tracebacks in the console of a working app.
- There is **no container or cloud config**, because none was specified. The app
  is a read-only local demo; publishing it would mean putting an unauthenticated
  assistant that reads a local financial corpus on a network, which is out of
  scope. If a hosted link is required for D-1, that is a deployment decision to
  make explicitly, with auth added first.

---

## 7. Known limits — honest list

**Corpus**

- **Point-in-time snapshot.** Values are as of each page's own `fetched_at`
  (2026-09-27 for all five). Fees, exit loads and benchmark names change.
- **Five pages only.** Losing one means the assistant silently lacks a whole
  scheme. Out-of-corpus questions are refused rather than answered from memory.
- **Corpus drift.** Nothing re-fetches automatically. Run `spike_fetch.py` then
  `ingest` again; idempotency means only changed pages are re-embedded.
- **Capital-gains statements are not answerable.** Measured 0/5 across the corpus
  (OD-4): the question type is absent from all five pages. It is treated as
  out-of-scope, not as a failure.
- **27% of the index is boilerplate.** 92 distinct chunk bodies appear on more
  than one page — 326 redundant copies of 1,193 chunks — because the corpus is
  five funds of one AMC. The duplicated glossary definition outranks the real
  `Expense ratio | 1.21%` fact row on BM25 term frequency. Collapsing duplicates
  at ingest would raise precision; deliberately not done (OQ-3).

**Model**

- **English only.** `all-MiniLM-L6-v2` is English-only. Hindi is not served, and
  cannot be without changing the mandated model (OD-6).
- **Generation requires a configured provider.** With `LLM_PROVIDER=none` the
  app still runs; every factual question refuses rather than answering from
  retrieval alone.
- **A single global threshold is a known weak point (OQ-4).** `raw_dense_max` is
  not comparable across question shapes: measured 0.8225 for a scheme-specific
  benchmark question but 0.2695 for a bare `lock-in period` question whose
  retrieved chunk was nonetheless correct. 0.7562 sits above that low tail, so
  genuinely-correct hard questions can be refused. A per-intent or
  per-question-shape threshold would be the fix.

**Safety**

- **`education_links.yml` ships EMPTY (OD-2).** Opinion refusals therefore carry
  `educational_link_missing=True` and the UI says so in words. No URL is ever
  generated, guessed or inferred — an unverified link is worse than no link. The
  refusal itself is unaffected; only the "read more" affordance is missing.
- **PAN has no checksum, because none is published (OD-9).** The Income Tax
  Department publishes no PAN check-digit algorithm. PAN is matched structurally
  (`AAAAA9999A`, published 4th-character entity code, placeholder rejection).
  Inventing a checksum would eventually reject *valid* PANs, which is the worse
  failure.
- **A bare 4–6 digit run is not treated as an OTP without a cue word (OD-10).**
  Measured over all 1,193 real chunks, literal bare-OTP detection flags 44
  (3.67%) — every hit a portfolio holding code like
  `GOVERNMENT OF INDIA 34238 GOI 22AP64`. A 3.67% false-positive rate on the
  assistant's own corpus makes it unusable, so an OTP needs a cue (`otp`,
  `verification code`, `pin`, …). **Known cost: a user who pastes only digits is
  not refused.**
- **`question_ref()` is a truncated SHA-256** for log correlation, not a keyed
  MAC. It is not a defence against an adversary who can guess candidate
  questions.

**Engineering**

- **`git` was not installed on the build machine.** `.gitignore` is written and
  correct but was never exercised. The primary defence against committing `.env`
  is git — install it before sharing this repository.
- **A non-answer can pass every check.** See `artifacts/prd_checklist.md`: in the
  recorded run, Q5 (benchmark of HDFC Balanced Advantage Fund) was *answered*
  with "The provided corpus does not contain the benchmark…" — while the
  benchmark is in the corpus and the gate opened at `raw_dense_max=0.8706`.
  Every output-level rule was satisfied. No deterministic check catches a
  confident non-answer, and the judge is the only thing that would.

---

## 8. Tests

```powershell
python -m pytest tests -q
```

**689 passed.** Coverage includes the truncation gate, ingest idempotency,
per-page provenance, gate-uses-raw-dense, the 7 named generation tests, PII
detection plus Verhoeff tested exhaustively, and the "nothing persisted" and
"LLM unreachable with un-scanned input" guarantees.

---

## 9. License / attribution

Corpus content is from Groww (public fund pages). This repository contains the
retrieval code only; it redistributes no page content beyond the local
`data/raw` extract, which is gitignored.