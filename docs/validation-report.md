# Validation Report — `PRD.md` v0.1 vs `problemstatement.txt`

| Field | Value |
| --- | --- |
| **Document** | Validation report, v0.2 — **supersedes v0.1** |
| **Target under review** | `docs/PRD.md` v0.1 |
| **Source of truth** | `docs/problemstatement.txt` (3,889 bytes, 55 lines) — **now present** |
| **Cross-checked against** | `docs/architecture.md` v0.1 |
| **Result** | 🔴 **FAIL — product mismatch.** PRD must be rewritten, not amended. |

---

## 0. Resolution Status — actions from §8 completed

| §8 action | Status | Done in |
| --- | --- | --- |
| 1. Fetch the 5 pages, confirm extractable text; audit 7 question types | ⏳ **Outstanding** — build milestone M0, blocks the pipeline | — |
| 2. Answer Q-1…Q-8 | ⏳ **Outstanding** — now tracked as **OD-1…OD-8** | `PRD.md` §17, `architecture.md` §14 |
| 3. Rewrite `PRD.md` as v0.2 | ✅ **Done** — 40 FRs, all 26 source requirements mapped, no gaps | `PRD.md` v0.2 |
| 4. Rewrite `architecture.md` as v0.2 | ✅ **Done** — fetch stage, two-stage intent gate, truncation gate, output validation, per-page `fetched_at` | `architecture.md` v0.2 |
| 5. Void v0.1's validation report | ✅ **Done** — this document is v0.2; v0.1 is void | — |

Also closed out from the §5 audit, in passing:
- **C-1** resolved — both documents now gate on the **raw dense score**; the PRD's §8.1 error is gone.
- **A-1** resolved — NFR-1 uses median ≤6 s / max ≤12 s over n=8, with p95 explicitly rejected as uncomputable.
- **A-2** resolved — the accuracy rubric is now defined in `PRD.md` §9.1, with the judge model/version required to be recorded.
- **A-3** resolved — citation correctness is expressed as an operational, checkable rule.
- **A-4, A-5** resolved — every metric has a denominator; cost is scoped to a demo run.
- **A-6** resolved — NFR-11 counts commands, NFR/M-10 measures wall-clock, install is separate.
- **A-7** resolved — the duplicated groundedness metric was merged.
- **A-8** resolved — sample-set composition fixed at 5 factual + 2 opinion + 1 unanswerable.
- **A-9, B-6** resolved — FR-36…FR-39 now own the five mandated artefacts, including the demo video.
- **B-1…B-5** resolved — cross-references corrected, priorities consistent with the cut order, milestone done-when excludes cuttable items, scale target sits below the non-goal boundary, dependencies promoted to Must.
- **C-2…C-6** resolved — scope is traceable, the API server was cut for a single process, mobile-web removed, coverage is an auditable table, and the architecture DoD is a strict subset of the PRD checklist.
- **Stale file references** resolved — the void `Problemstatment.txt` / `Prompt.txt` pointers no longer appear in either document.

**The two open decisions that still block a build:** **OD-2** (source of the educational links for opinion refusals — do not fabricate URLs) and **OD-4** (the capital-gains-statement corpus gap). **OD-1** (chat LLM) is no longer architecturally blocking, since the `LLMClient` adapter makes it a config choice.

---

## 1. Verdict

### 1.1 The source is now readable, and it describes a different product

| | `problemstatement.txt` (source) | `PRD.md` v0.1 (under review) |
| --- | --- | --- |
| **Product** | Mutual Fund FAQ assistant — facts-only Q&A | Course-material chatbot for students |
| **Corpus** | **5 public web pages** (HDFC schemes on Groww) | Local `data/` folder of `.pdf`/`.docx`/`.md`/`.txt` |
| **Users** | Retail MF investors; support/content teams | Students in a class; TA/professor |
| **Domain** | **Financial services** — exit load, lock-in, expense ratio, riskometer | Education — deadlines, rubrics, formulas |
| **Compliance regime** | No PII · no advice · no performance claims · public sources only | None |
| **Answer shape** | **≤ 3 sentences, one source URL, "Last updated from sources:"** | Unbounded length, local file + page citation |
| **Refusal trigger** | **Opinionated/portfolio questions** ("Should I buy?") | **Low retrieval confidence** |
| **Mandated stack** | **`all-MiniLM-L6-v2`**, **ChromaDB** | `text-embedding-3-small`, Chroma, LangChain, FastAPI, Streamlit |
| **Scale** | 5 pages | 500 docs / 50 k chunks |
| **Deliverables** | 5 artefacts | 1 (prototype) |

**These do not overlap enough to patch.** The PRD's problem framing, users, corpus, retrieval targets, refusal logic, answer contract, stack, risks, milestones, and demo script are all built for the wrong product. Only the *retrieval engineering* survives.

⚠️ **The prior validation report (v0.1) is void.** It concluded "⛔ BLOCKED" against an empty file and described a course-RAG PRD. Do not cite it.

### 1.2 Scorecard

| Area | Result |
| --- | --- |
| Product / problem framing (§1) | 🔴 Wrong product |
| Goal & non-goals (§2) | 🔴 Missing 3 mandatory constraints |
| Users (§3) | 🔴 Wrong personas |
| User flow (§4) | 🔴 Wrong flow (no refusal-on-opinion case) |
| Functional requirements (§5) | 🔴 9 of 25 contradicted or absent |
| Non-functional requirements (§6) | 🔴 4 contradicted; 3 absent |
| Success metrics (§7) | 🔴 Metrics measure the wrong outcome |
| Technical approach (§8) | 🔴 2 of 3 mandated-stack items wrong |
| Risks (§10) | ⚠️ Real risks omitted; irrelevant ones added |
| Delivery plan (§11) | 🔴 Wrong deliverable set |
| Demo script (§12) | ⚠️ 5 min vs mandated ≤3 min |
| Vector store choice | ✅ Chroma — the one match |
| Retrieval engineering | ✅ Largely sound, carries over |

---

## 2. Requirement Traceability

`PS-*` = source requirement, quoted or closely paraphrased. Severity: 🔴 must fix · ⚠️ material · ✅ covered

### 2.1 Scope & corpus

| # | Source requirement | PRD status | Severity |
| --- | --- | --- | --- |
| PS-1 | Pick **one AMC (HDFC)** and **3–5 schemes** under it | Not present — PRD corpus is unbounded and open-ended | 🔴 |
| PS-2 | **5 named schemes**, all Direct–Growth: Large Cap, Flexi Cap, ELSS Tax Saver, Small Cap, Balanced Advantage (Hybrid) | Absent | 🔴 |
| PS-3 | Corpus is the **5 public web pages** | FR-1 specifies a **local file folder** — direct contradiction | 🔴 |
| PS-4 | May also draw on **AMC/SEBI/AMFI** pages (factsheets, KIM/SID, scheme FAQs, fee/charges, riskometer/benchmark notes, statement/tax-doc guides) | Absent — no allowance for a broader corpus | ⚠️ |
| PS-5 | **Public sources only**; no screenshots of the app back-end; **no third-party blogs** | Absent | 🔴 |
| PS-6 | Deliverable: **source list (CSV/MD) of the URLs used** | Absent from §11 and §14 | 🔴 |

### 2.2 Answer contract

| # | Source requirement | PRD status | Severity |
| --- | --- | --- | --- |
| PS-7 | **Every answer must include one source link** | FR-12 requires inline citation *markers* resolved to local file+page. No URL anywhere | 🔴 |
| PS-8 | **Answers ≤ 3 sentences** | No length constraint anywhere | 🔴 |
| PS-9 | Append **"Last updated from sources: "** | Absent | 🔴 |
| PS-10 | Answer the 7 named fact types: expense ratio, exit load, minimum SIP, ELSS lock-in, riskometer, benchmark, capital-gains statement download | FR-1…FR-25 are generic; none of these 7 is a named requirement | 🔴 |
| PS-11 | **No performance claims** — do not compute/compare returns; link the official factsheet if asked | Absent. This is a hard prohibition and the PRD has no concept of it | 🔴 |
| PS-12 | **No PII** — do not accept or store PAN, Aadhaar, account numbers, OTPs, emails, phone numbers | Absent. PRD has no input filtering, no storage policy | 🔴 |

### 2.3 Refusal behaviour

| # | Source requirement | PRD status | Severity |
| --- | --- | --- | --- |
| PS-13 | **Refuse opinionated/portfolio questions** ("Should I buy/sell?") with a polite, facts-only message | FR-11 refuses on *insufficient context* — a different trigger entirely. Opinion questions retrieve *plenty* of context and would be answered confidently | 🔴 |
| PS-14 | Refusal must include **a relevant educational link** | FR-11 returns a fixed string. A static string cannot return a *relevant* link | 🔴 — see §4.1, this breaks the architecture |
| PS-15 | **No investment advice** | Absent | 🔴 |

### 2.4 UI

| # | Source requirement | PRD status | Severity |
| --- | --- | --- | --- |
| PS-16 | **Tiny UI**: welcome line + **3 example questions** + note "Facts-only. No investment advice." | FR-16…FR-22 specify a full chat app with history, clear, thumbs feedback, manifest, debug toggle. Materially over-built against an explicit "tiny UI" instruction | ⚠️ |
| PS-17 | **Disclaimer snippet** used in the UI | Absent from §11 and §14 | 🔴 |

### 2.5 Mandated architecture

| # | Source requirement | PRD status | Severity |
| --- | --- | --- | --- |
| PS-18 | Follow all RAG stages: **Loading → Chunking → Embedding → storing vector data** | FR-1…FR-5 cover this. ✅ | ✅ |
| PS-19 | Data **ingestion + data retrieval** both demonstrated | ✅ covered | ✅ |
| PS-20 | Embedding model: **`sentence-transformers/all-MiniLM-L6-v2`** | §8 specifies OpenAI **`text-embedding-3-small`** — directly contradicts a mandated model | 🔴 |
| PS-21 | Chunking strategy: recursive/semantic, decided based on the data | FR-2 fixes ~500 tokens with no stated rationale. Must be re-derived; see §4.2 for why 500 is now infeasible | 🔴 |
| PS-22 | Vector DB: **ChromaDB** | §8 specifies Chroma | ✅ |

### 2.6 Deliverables

| # | Source requirement | PRD status | Severity |
| --- | --- | --- | --- |
| PS-23 | Working prototype link (app/notebook) **or ≤3-min demo video** if hosting isn't possible | §12 scripts a **5-minute live demo**. Neither artefact is specified | 🔴 |
| PS-24 | **README** with setup steps, **scope (AMC + schemes)**, known limits | FR-9/M6 partially cover setup; scope statement absent | ⚠️ |
| PS-25 | **Sample Q&A file, 5–10 queries** with answers + links | FR-23 requires a 20–30 question gold set. Different artefact, ~3× the size, and the PRD omits the *deliverable* framing entirely | ⚠️ |
| PS-26 | End output: RAG ChatBot | ✅ | ✅ |

**Traceability total: 2 of 26 source requirements fully satisfied.** One (`PS-18`) is accidental — the PRD described a generic RAG pipeline, and so did the source.

---

## 3. Conflicts on the Mandated Stack

| Component | Source (mandated) | PRD v0.1 | Action |
| --- | --- | --- | --- |
| Embeddings | `all-MiniLM-L6-v2` (HuggingFace, **local**, 384-dim) | `text-embedding-3-small` (OpenAI, **API**, 1536-dim) | Replace. Removes the embedding API cost and the OpenAI-key dependency for that stage |
| Vector DB | ChromaDB | Chroma | Keep |
| Chat LLM | **Not specified** | `gpt-4o-mini` | Cannot be "validated" — this is my inference, not a source requirement. Needs your decision |
| Chunking | Decide from the data | Fixed 500 tokens | Re-derive — 500 is infeasible, see §4.2 |
| Framework | Not specified | LangChain | Optional |
| UI | "tiny UI", app **or notebook** | FastAPI + Streamlit | Over-built; a notebook may satisfy the brief more cheaply |
| Corpus load | Fetch 5 web pages | Read local files | Needs a new ingestion stage — see §4.4 |

**Net effect on NFR-8 and NFR-10:** both were premised on "one LLM API key". With a local embedder, only the *generation* model needs a key. If that is also local, the project has **no external dependency at all** — a materially stronger position, and one the PRD should claim once decided.

---

## 4. Architectural Consequences

### 4.1 🔴 The refusal path must change, and it invalidates `architecture.md` §6.2

This is the most consequential finding.

`architecture.md` §6.2 implements refusal as a **confidence gate that short-circuits before the LLM is called**, on the reasoning that a fixed string is deterministic and demo-safe. That directly fails **PS-14**: a refusal must supply *a relevant educational link*, which requires retrieval to have happened and to have produced a useful result. A static string cannot do that.

The source therefore specifies **two structurally different refusals**, and the PRD/architecture has room for one:

| Refusal type | Trigger | Needs retrieval? | Needs LLM? | Output |
| --- | --- | --- | --- | --- |
| **Out-of-scope** | "Should I buy HDFC Large Cap?" | **Yes** — to find the educational link | Yes, to phrase it | Facts-only message + relevant educational link |
| **Not in corpus** | Expense ratio of a scheme we don't cover | Optional | No | Fixed message (current design still valid here) |

Note that "Should I buy?" will retrieve *plenty* of highly-similar context — expense ratios and returns are exactly what those pages contain. **A similarity threshold will not catch it.** Detecting advice-seeking requires either an intent classifier or an LLM-side instruction plus a post-hoc check. This is a real engineering problem the PRD never posed.

**Recommendation:** an `intent` field on `GroundedAnswer` (`factual` | `opinion` | `out_of_scope`), decided before generation, with the opinion branch running retrieval to source the educational link. The current gate stays, but it is no longer the whole refusal story.

### 4.2 🔴 `all-MiniLM-L6-v2` makes 500-token chunks infeasible

`sentence-transformers` ships `all-MiniLM-L6-v2` with **`max_seq_length=256`**. Anything longer is **silently truncated at embedding time** — no error, no warning. The failure mode is specific and nasty for this product: a chunk whose expense-ratio table or exit-load schedule sits past token 256 gets embedded with its tail missing, retrieval then returns it as a strong match, and the LLM answers from a fact that was never in the vector. A hallucination with a real citation attached — the exact outcome **PS-11** exists to prevent.

**Required changes:**
- `CHUNK_SIZE` ≤ ~200 tokens, not 500.
- Assert at embed time that `len(tokenizer.encode(chunk)) <= max_seq_length`, and **fail loudly** on violation. Silent truncation must be impossible.
- Because the model truncates rather than erroring, this belongs in `ingest/writer.py` as a hard gate, not a log line.
- Re-derive the chunking strategy on the **actual page HTML**, per PS-21.

Also relevant: 384-dim vectors and a model optimised for short symmetric similarity. Financial pages are tables and long prose, so per-chunk relevance will be noisier than with a modern embedding model. Expect to lean on BM25 for exact lookups (§4.5).

### 4.3 The answer becomes a structured object, not prose

PS-7, PS-8, PS-9, PS-11, PS-15 together mean every answer conforms to a fixed contract. Free-form generation followed by citation-stripping is no longer sufficient — the constraints must be **enforced and validated**:

```
answer (≤3 sentences) · source_url (exactly one) · last_updated · is_advice (must be false) · intent
```

`is_advice` needs a check, not just a prompt instruction: a keyword/intent screen on the generated text (buy/sell/suggest/recommend/should I/portfolio) that trips the refusal branch. Prompting alone is not sufficient for a stated prohibition — and the PRD's own §10 already concedes that models ignore instructions.

**Sentence count must be validated, not requested.** Counting after generation and retrying once is cheap and makes NFR-style compliance measurable.

### 4.4 Ingestion needs a new first stage

FR-1 assumes files on disk. PS-3 requires fetching 5 live pages. A `fetch` stage is needed ahead of load, and it carries risks the PRD never considered:

- **Groww pages are client-rendered.** A naive HTTP GET may return a JS shell with little text. Each page must be verified to yield sufficient extractable content, and a rendered-fetch fallback may be required. **This is the most likely reason the project stalls** — verify all 5 pages yield usable text *before* building anything else.
- **Robots/ToS and rate limiting.** Public pages, but scraping needs care. One-time fetch at build time is both compliant and simpler than live fetching.
- **Content drift.** Expense ratios change. This is precisely why PS-9 mandates "Last updated from sources:" — so the **retrieval timestamp must be persisted per source** and surfaced. It also means a re-fetch cadence is a real product decision, and the manifest must record per-URL fetch time, not one global timestamp.
- **Per-page provenance becomes mandatory**, because the answer's citation is a URL (PS-7) and the "last updated" date is per-source (PS-9).

### 4.5 Good news: hybrid retrieval matters more, not less

The PRD's FR-7 (dense + BM25, RRF) was a "Should"/stretch item. Here it should be promoted. The questions are exact-match lookups against structured values — expense ratio `1.12%`, exit load `< 1% if held > 12 months`, SIP `₹500`, lock-in `3 years`. Dense retrieval is weak on precise numerics and dates; BM25 is strong on them. The PRD's own ADR-4 (RRF, no score calibration needed) is exactly right here.

Corollary: §6.2's correction still stands — threshold the **raw dense score**, not the RRF score.

### 4.6 Corpus may not cover the questions the source asks for

The source names 7 example question types, but the corpus is 5 *scheme* pages:

| Question type | Likely covered by a scheme page? |
| --- | --- |
| Expense ratio | ✅ |
| Exit load | ✅ |
| Minimum SIP | ✅ |
| ELSS lock-in (3 years) | ✅ |
| Riskometer | ⚠️ varies by page |
| Benchmark | ⚠️ varies by page |
| **How to download a capital-gains statement** | ❌ **account-level, not scheme-level — not on a scheme page** |

The last one is a **Groww account help topic**, not an HDFC scheme fact. Under this corpus it is unanswerable. This matters because the source explicitly lists it as an example question, so a demo featuring it would show a refusal on a question the brief expects answered.

**Action:** audit all 5 pages against the 7 question types *first*. PS-4 permits adding AMC/SEBI/AMFI pages (factsheets, statement/tax-doc guides) — this is the sanctioned way to close the gap. Either extend the corpus or consciously drop that question type, and document which.

---

## 5. Findings From the v0.1 Audit That Still Apply

These are independent of the source and remain valid:

| ID | Finding | Still applies? |
| --- | --- | --- |
| A-1 | p95 not computable from a 25-question gold set | ✅ Yes — and PS-25 wants only 5–10 queries, so it is worse |
| A-2 | LLM-judge rubric referenced but never defined | ✅ Yes |
| A-3 | FR-12 untestable as written | ✅ Yes — replaced by §4.3, now measurable |
| A-4 | M-4 has no denominator | ✅ Yes |
| A-5 | NFR-10 undefined unit | ⚠️ Partly — now cheaper, since local embeddings cost nothing |
| A-6 | NFR-9 (commands) vs M-6 (minutes) measure different things | ✅ Yes |
| A-7 | NFR-4 duplicates M-2 | ✅ Yes |
| A-9 | No FR owns the demo fallback recording | ✅ **More relevant** — PS-23 makes the video a primary deliverable |
| B-1 | §4 cross-reference points at FR-6/M-4 instead of FR-8/FR-11 | ✅ Yes |
| B-2 | FR-19 "Must" but in the cut order | ✅ Yes |
| B-3 | M2's done-when includes cuttable FR-7 | ✅ Yes |
| B-4 | NFR-6 target sits on the non-goal boundary | ✅ Yes |
| B-5 | "Should" items are hard dependencies | ✅ Yes |
| B-6 | NFR-9 has no owning FR | ✅ Yes |
| C-1 | PRD §8.1 thresholds the fused score; architecture §6.2 says that's wrong | ✅ **Still unresolved** — and now more consequential, since hybrid search is being promoted |
| C-2 | Architecture adds untraceable scope | ✅ Yes — needs a fresh pass |
| C-3 | Two processes vs three-command budget | ⚠️ Muted — "tiny UI" suggests dropping FastAPI anyway |
| C-4 | Mobile web vs loopback bind | ❌ Superseded — the PRD is being rewritten |
| C-5 | Architecture overstates coverage | ✅ Yes |
| C-6 | Two divergent DoD lists | ✅ Yes |
| **new** | PRD.md lines 10 and 264 reference `docs/Problemstatment.txt` and `Prompt.txt` — **neither exists**. The file is now `problemstatement.txt` | ✅ Yes — two dangling references |

---

## 6. What Survives

Not everything is wasted. Carry these forward:

| Keep | Why |
| --- | --- |
| **Chroma choice** | Mandated — the one clean match |
| **Hybrid retrieval + RRF fusion** | Now a priority, not a stretch (§4.5) |
| **Raw-dense-score confidence gate** | More important here, not less — and §6.2's correction stands |
| **Citation resolution from metadata, never from model text** | Directly serves PS-7/PS-9/PS-11 |
| **Idempotent, hash-keyed ingestion** | Web pages drift, so re-fetch + change detection is now essential (§4.4) |
| **Corpus manifest concept** | Becomes a **per-URL** manifest with fetch timestamps (PS-9) |
| **Typed `GroundedAnswer` contract** | Correct instinct; needs new fields (§4.3) |
| **Eval harness + `make eval`** | PS-25 still wants a sample Q&A file; the harness produces it |
| **Repo layout, `Makefile`, `src/` structure** | Unaffected |
| **Anti-hallucination framing as the core claim** | Correct priority — but the stakes are now user money, not a class mark |
| **Localhost-bind + no-auth posture** | Still right given no PII is stored |
| **All of Part A/B/C bookkeeping fixes** | §5 |

---

## 7. Ambiguities in the Source — Decisions Needed

Genuine gaps in `problemstatement.txt`. I have **not** invented answers; each needs your call.

| # | Ambiguity | Why it matters |
| --- | --- | --- |
| Q-1 | **Which chat LLM?** The source mandates only the *embedding* model. | Determines whether the project needs an API key at all, and whether NFR-8's "no cloud account" claim survives. Biggest single open decision |
| Q-2 | **Is the corpus exactly 5 pages, or 5 + more?** Line 27 permits AMC/SEBI/AMFI pages; the deliverable says "the 5 URLs you used" | Decides whether the capital-gains-statement gap (§4.6) is a corpus extension or a dropped question type |
| Q-3 | **"One source link" — exactly one, or at least one?** | Affects multi-source answers (e.g. ELSS lock-in + tax doc). Enforceable as a schema constraint either way |
| Q-4 | **Live fetch or build-time snapshot?** | Source implies "collect the pages" → build-time. But PS-9's "last updated" implies ongoing freshness |
| Q-5 | **What counts as a "relevant educational link"** for an opinion refusal? | Needs a source in the corpus, which is scheme pages — not educational content. May require adding AMC investor-education pages (PS-4) or a curated link map |
| Q-6 | **Language — English only, or Hindi?** Unspecified. Groww is India-facing | `all-MiniLM-L6-v2` is **English-only**; Hindi retrieval will be poor without a multilingual model, which would break a mandated choice |
| Q-7 | **Hosting possible?** PS-23 allows a ≤3-min video instead | Determines whether `FastAPI`+hosting is worth the complexity |
| Q-8 | **Is a notebook acceptable as the prototype?** PS-23 says "app/notebook" | A notebook could remove the entire UI layer — a large scope saving against "tiny UI" |

**Q-5 is the one I'd flag hardest.** The refusal must cite educational material, but the sanctioned corpus is 5 commercial scheme pages. Without resolving this, the opinion-refusal path either has no link to give or reaches outside the corpus — violating PS-5. Resolve it before building that path.

---

## 8. Recommended Next Actions

1. **Fetch the 5 pages and confirm each yields usable text** (§4.4). This is a 30-minute task that can invalidate the whole plan, so it precedes everything else. Also audit the 7 question types against the 5 pages (§4.6).
2. **Answer Q-1…Q-8.** Q-1 and Q-5 block architecture; Q-2 and Q-6 block corpus.
3. **Rewrite `PRD.md` as v0.2** — a fresh document, not an amendment. Only §5's surviving items carry over. Fix the v0.1 bookkeeping defects in passing.
4. **Rewrite `architecture.md` as v0.2** — chiefly: replace the single-refusal gate with the two-type intent model (§4.1), re-derive chunking for a 256-token model with a hard truncation guard (§4.2), add the fetch stage (§4.4), and restructure the answer contract (§4.3).
5. **Delete or clearly void v0.1's validation report** so nobody cites a report that describes the wrong product.

Steps 1–2 are prerequisites; 3–5 can proceed in parallel by different people.

---

*End of validation report v0.2. Verdict: 🔴 FAIL — product mismatch; 2 of 26 source requirements met. `PRD.md` requires a rewrite, not amendment. This report supersedes v0.1, which was conducted against an empty source file and is void.*
