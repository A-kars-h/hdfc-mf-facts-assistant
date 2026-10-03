# PRD §18 Acceptance Checklist — honest item-by-item report

Generated for Phase 8. Every line is marked from something that was actually
checked, not from intention. Where an item is not satisfied, it says so and says
what is missing.

**Legend:** ✅ verified · ⚠️ partial — works but a stated sub-condition fails ·
❌ not satisfied · ⬜ unverifiable in this environment

**How each claim was checked:** the full test suite (`python -m pytest tests -q`,
689 passed), a live 8-query eval run against the real index and a live LLM
(`artifacts/sample_qa.md`, raw capture in `artifacts/eval_run_capture.json`),
the files on disk, and — for anything about what the UI shows — the real
`src/ragbot/ui/app.py` driven through Streamlit's `AppTest` and transcribed
(`artifacts/screenshots/`).

---

## Corpus & scope

| # | Item | Status | Evidence |
|---|---|---|---|
| 1 | All 5 HDFC schemes in scope, all Direct "Growth" | ✅ | `config/corpus.yaml`; all 5 rows `Direct Growth` / `Direct Plan - Growth`; `artifacts/source_list.csv` |
| 2 | Every page yielded usable text; FR-2 gate never bypassed | ✅ | `artifacts/spike_report.md` 5/5 PASS, 7,586–33,158 chars each; `ingest/clean.py` raises `EmptyPageError` below 1,500 |
| 3 | No third-party blog or non-public source in the corpus | ✅ | all 5 URLs are `groww.in/mutual-funds/...`; no other URL appears in `source_list.csv` |
| 4 | Capital-gains-statement question resolved (OD-4) | ✅ | measured **0/5** absent from the corpus. Recorded as out-of-scope, not as a failure. `docs/implementation.md` OD-4 |

## Mandated architecture

| # | Item | Status | Evidence |
|---|---|---|---|
| 5 | `all-MiniLM-L6-v2` used for embeddings, no substitution | ✅ | read from the loaded model at runtime; recorded in `artifacts/manifest.json` (`embedding_model`, `embedding_dim=384`) |
| 6 | ChromaDB used as the vector store | ✅ | `ingest/writer.py` → `chromadb.PersistentClient`, collection `mf_faq` |
| 7 | All four RAG stages demonstrable + retrieval | ✅ | `fetch → clean → chunker → embedder → writer`; `retrieval/` has dense + sparse + fusion + gate |
| 8 | Chunk size ≤200 tokens; oversized chunk **fails loudly** | ✅ | `ChunkTooLongError(tokens, ceiling)` raised before encoding; `test_truncation_gate` |
| 9 | No chunk silently truncated | ✅ | the tokenizer count is asserted against `model.max_seq_length` **before** `encode()` is called, so the library's silent-truncation path is unreachable |

## Answer contract

| # | Item | Status | Evidence |
|---|---|---|---|
| 10 | Every answer ≤3 sentences | ✅ | M-6 = 5/5 factual, 5/5 in the live run; enforced in `generation/validate.py` and on the `Answer` model itself |
| 11 | Exactly one source link, in-corpus | ✅ | M-2 = 10/10 measured; model-emitted URLs stripped and re-resolved from chunk provenance |
| 12 | Every answer shows its own page's `Last updated from sources:` | ✅ | per-page `fetched_at` in the manifest; `ui/app.py::_render_source`; all 5 answered queries carry a distinct per-page date |
| 13 | No answer contains advice (M-4 = 0) | ✅ | M-4 = **0/8** measured in the live run; advice screen on the output |
| 14 | No answer contains a return, NAV or CAGR figure (M-5 = 0) | ✅ | M-5 = **0/8** measured; the screen targets return-*shaped* figures so a 1.03% expense ratio still passes |

## Refusal

| # | Item | Status | Evidence |
|---|---|---|---|
| 15 | "Should I buy/sell?" refused politely, **with** a verified educational link | ⚠️ **half fails** | The refusal happens and is polite and non-apologetic. **The educational link does not exist**: `config/education_links.yml` ships `links: {}` (OD-2). The answer sets `educational_link_missing=True` and the UI says so in words. Invariant 10 forbids inventing a URL, so this cannot be "fixed" without a human verifying real URLs. **Resolving OD-2 is the only way this line becomes ✅** |
| 16 | "Which fund is best?" refused, no performance comparison | ✅ | Q7 refused, intent `opinion`; M-5 = 0 |
| 17 | A real HDFC scheme outside the corpus is declined, not answered from memory | ✅ | Q8 (HDFC Mid Cap — a real HDFC scheme, deliberately out of corpus) → Refusal B; also covered by `test_unanswerable_real_scheme_is_refused` |
| 18 | Refusals never expose thresholds, scores or chunk internals | ✅ | `ui/app.py` renders the chunk inspector for **answered** questions only; `check_refusal_leaks_nothing` passes; the threshold value is never displayed |

## Safety

| # | Item | Status | Evidence |
|---|---|---|---|
| 19 | PAN / Aadhaar / account / OTP / email / phone → not embedded, not sent, not stored | ✅ | scan runs before embed, before the LLM, before any log write; `_route`/`_generate` raise `UnscannedInputError` unless handed a real, enforced `PIIResult` |
| 20 | Logs contain no PII (NFR-9) | ✅ | `test_nothing_persisted…`, `test_no_secret_reaches_the_log`, `test_pii_is_absent_from_artifact_and_raw_directories`; `redact()` delegates to the detector |

## UI

| # | Item | Status | Evidence |
|---|---|---|---|
| 21 | Welcome line, input, message area | ✅ | `ui/app.py::main` — title, `WELCOME` caption, `st.chat_input`, chat messages |
| 22 | Exactly 3 example questions | ✅ | `EXAMPLE_QUESTIONS` is a 3-tuple; rendered as 3 buttons; they are the golden-set queries Q3/Q6/Q8, not invented strings |
| 23 | "Facts-only. No investment advice." note visible | ✅ | `DISCLAIMER` constant, `st.info(...)` re-rendered on **every** rerun — persistent, not a one-time banner. The literal string is `artifacts/disclaimer_snippet.md` |
| 24 | Retrieved chunks inspectable on demand (FR-28) | ✅ | `st.expander("Show retrieved chunks (N sent to the model)")`, shows raw dense / fused rank / BM25 and the full chunk text. Rendered in `artifacts/screenshots/05_chunk_inspector.md` |

## Evaluation & deliverables

| # | Item | Status | Evidence |
|---|---|---|---|
| 25 | Sample Q&A: 8 queries (5 factual, 2 opinion, 1 unanswerable) with answers + links | ✅ | `artifacts/sample_qa.md`, **generated from a live eval run**, not hand-written. Composition guarded by `_guard_composition` |
| 26 | Metrics M-1–M-7 reported, judge model **+ version** recorded | ✅ | `artifacts/eval_report.md`: M-1 = 1.60/2 over 5 factual; judge model `qwen/qwen3.8-27b`, rubric `PRD-9.1-v1`, judge prompt SHA-256 `4d622d6b36aaef02` |
| 27 | Accuracy rubric defined and stored in-repo | ✅ | rubric is `PRD-9.1-v1`; the judge prompt is in `src/ragbot/eval/judge.py::build_messages`, fingerprint via `prompt_fingerprint()` |
| 28 | D-1 prototype link **or** ≤3-min demo video | ✅ **now satisfied** | **Recording:** [HDFC MF facts assistant - Demo video.mp4](https://drive.google.com/file/d/1wG_o83w-RLmd-N0AX-HHjm1Bt15drxhJ/view?usp=sharing) — Google Drive, shared "anyone with the link" (verified: Drive serves its virus-scan interstitial only for public files; a private one returns an access page). **Duration verified from the file's own `mvhd` atom, not from the filename:** 162.58 s = **2m 42.6s**, within the 3-minute limit. Reproduce with `python scripts/verify_demo_duration.py 1wG_o83w-RLmd-N0AX-HHjm1Bt15drxhJ` |
| 29 | D-2 source list in CSV **and** MD | ✅ | `artifacts/source_list.csv` + `artifacts/source_list.md`, both generated from `config/corpus.yaml` × `artifacts/manifest.json` |
| 30 | D-3 README with setup, scope, honest known limits | ✅ | `README.md` — §2 setup, §1 scope, §7 a limits list that includes the English-only limit, the empty education-link map, OD-9/OD-10, and the Q5 non-answer |
| 31 | D-4 sample Q&A file | ✅ | `artifacts/sample_qa.md` |
| 32 | D-5 disclaimer snippet | ✅ | `artifacts/disclaimer_snippet.md`, quoting the `DISCLAIMER` constant verbatim |

## Engineering

| # | Item | Status | Evidence |
|---|---|---|---|
| 33 | No API key in code; `.env.example` present, `.env` ignored | ✅ | `.env.example` has `LLM_API_KEY=` blank and no real value; `.gitignore` lists `.env`; a real key exists only in the local `.env`, which is gitignored |
| 34 | Clean clone → running app in ≤3 commands, excluding install (NFR-11) | ✅ as commands / ⚠️ as a verified clean-clone | The three commands are documented in `README.md` §2.4 and each was run in this workspace. **But this was never verified from a genuinely clean clone**: `git` is not installed on this machine, `data/raw` and `data/chroma` are already populated, and `make` is unavailable (the Makefile's recipes were verified individually instead). So "≤3 commands" is demonstrated, "clean clone → 3 commands" is not |
| 35 | Demo run recorded and ≤3 min; full run rehearsed twice | ✅ **complete** | **Recorded:** [HDFC MF facts assistant - Demo video.mp4](https://drive.google.com/file/d/1wG_o83w-RLmd-N0AX-HHjm1Bt15drxhJ/view?usp=sharing), publicly shared. **≤3 min independently verified** from the file's own `mvhd` atom — 162.58 s = 2m 42.6s (`python scripts/verify_demo_duration.py 1wG_o83w-RLmd-N0AX-HHjm1Bt15drxhJ`). **Rehearsed twice before recording** — attested by the author, confirmed 2026-10-03. Rehearsal is a human discipline with no artefact behind it, so this half rests on that attestation rather than on anything checkable from the file; the duration half does not |

---

## Summary

**27 ✅ · 2 ⚠️ · 0 ❌**

Both D-1 items are closed. The recording is public, and **≤3 min is verified from
the file's own `mvhd` atom** — 2m 42.6s, not a claim taken from a filename.

What remains partial is stated as partial:

- **Line 15** — the opinion refusal is correct in every respect except that no
  educational link exists, because `education_links.yml` ships empty (OD-2). The
  system refuses anyway and says so. It cannot be completed without a human
  verifying real, official URLs; generating them is forbidden by invariant 10.
- **Line 34** — the commands are correct and were run, but a genuinely clean
  clone was never tested, because `git` and `make` are both absent from this
  machine.

Line 35 is marked a complete pass on the strength of the author's confirmation
that the run was rehearsed twice before recording. That is recorded as an
attestation, not upgraded to "machine-verified" — the distinction is kept visible
so a later reader knows which half of that line rests on what.

## One finding worth acting on

**A confident non-answer passes every automated check.** In the live run, Q5
("What is the benchmark of HDFC Balanced Advantage Fund Direct Growth?") was
**answered, not refused**, with the text *"The provided corpus does not contain the
benchmark for HDFC Balanced Advantage Fund - Direct Growth."* — while the
benchmark **is** in the corpus (verified in Phase 0: NIFTY 50 Hybrid Composite
Debt 50:50), the gate opened at `raw_dense_max=0.8706`, and a citation to the
correct page was attached.

Every deterministic rule was satisfied: one in-corpus link, one sentence, no
advice, no return figure, correct `last_updated`. `run_checks` reported no
failures. Nothing in the harness can distinguish this from a good answer — only
the M-1 judge can, which is why M-1 exists.

This is a genuine gap in the eval harness, not a one-off. It is recorded here
rather than fixed, because fixing it means adding a factual-answerability check to
`eval/checks.py`, which is Phase 6 product code and outside Phase 8's remit to
change silently.

## A second, cosmetic finding

In `artifacts/screenshots/05_chunk_inspector.md`, every chunk retrieved for the
ELSS minimum-SIP question carries the section label **`Fund house`**, while the
chunk bodies are the correct fact rows (`Min. for SIP | ₹500`). The label comes
from the enclosing container in the page HTML, so the chunker records the wrong
section for fact rows in the fund-details grid. The answer and the citation are
correct — the label is only display metadata, and the chunk text is what the model
reads — but it is misleading in the inspector, which is the one place a reviewer
looks to check provenance. Phase 2 owns `chunker.py`'s section attribution; it is
recorded here rather than changed.