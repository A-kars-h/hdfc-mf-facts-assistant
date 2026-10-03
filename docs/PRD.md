# PRD — Mutual Fund FAQ Assistant (Facts-Only RAG Chatbot)

| Field | Value |
| --- | --- |
| **Document** | Product Requirements, **v0.2** |
| **Supersedes** | v0.1 (course-material chatbot) — **void, do not cite** |
| **Source of truth** | `docs/problemstatement.txt` (55 lines) |
| **Target** | Class milestone submission: working prototype **or** ≤3-min demo video |
| **Traceability** | Every `FR-*` cites a `PS-*` source line. 26 source requirements, all mapped (§16) |

> **Why v0.2 exists:** v0.1 was written against an empty source file and specified a course-material chatbot — a different product in a different domain. v0.2 is rebuilt from `problemstatement.txt`. Only the retrieval engineering carried over.

---

## 1. Problem & Product

### 1.1 Problem
Retail investors and support staff ask repetitive, factual questions about mutual fund schemes — expense ratio, exit load, minimum SIP, ELSS lock-in, riskometer, benchmark, how to fetch a statement. The answers live on public scheme pages, but each investor must find the right page, find the right field, and interpret it unaided. Support teams answer the same questions repeatedly by hand.

The failure mode that matters: these are **financial facts acted on with real money**. A wrong exit load or a misread lock-in period has a direct cost to the user. So the product's value is not fluency — it is **being reliably factual, visibly sourced, and refusing to advise**.

### 1.2 Product
A **facts-only FAQ assistant** over a closed corpus of public HDFC AMC scheme pages. Every answer is ≤3 sentences, carries exactly one source link, is stamped with when that source was last fetched, and contains no advice and no performance claim. Opinion and portfolio questions are refused politely, with a relevant educational link.

### 1.3 The one-sentence claim for the demo
> "It answers from five HDFC scheme pages, shows you which page and when it was read — and when you ask it whether to buy, it declines and teaches you instead."

---

## 2. Scope

### 2.1 AMC and schemes (fixed, from source lines 3–12, 26–32)

**AMC: HDFC Asset Management.** Five schemes, all **Direct – Growth** plans:

| # | Category | Scheme | Source URL |
| --- | --- | --- | --- |
| S1 | Large Cap | HDFC Large Cap Fund – Direct Growth | `https://groww.in/mutual-funds/hdfc-large-cap-fund-direct-growth` |
| S2 | Flexi Cap | HDFC Equity Fund – Direct Growth | `https://groww.in/mutual-funds/hdfc-equity-fund-direct-growth` |
| S3 | ELSS | HDFC ELSS Tax Saver Fund – Direct Plan – Growth | `https://groww.in/mutual-funds/hdfc-elss-tax-saver-fund-direct-plan-growth` |
| S4 | Small Cap | HDFC Small Cap Fund – Direct Growth | `https://groww.in/mutual-funds/hdfc-small-cap-fund-direct-growth` |
| S5 | Balanced Advantage (Hybrid) | HDFC Balanced Advantage Fund – Direct Growth | `https://groww.in/mutual-funds/hdfc-balanced-advantage-fund-direct-growth` |

The AMC is **not** configurable. Five schemes is both the floor and the ceiling for the committed scope.

### 2.2 Corpus

**Committed baseline: the 5 URLs above.** Source line 27 additionally permits pages from **AMC / SEBI / AMFI** — factsheets, KIM/SID, scheme FAQs, fee & charges pages, riskometer & benchmark notes, statement and tax-document guides. These are **extensions**, permitted but not committed. See §2.3.

### 2.3 ⚠️ Known corpus gap — capital-gains statements

The source names seven example question types (line 34). Six map onto a *scheme* page. The seventh does not:

| Question type | Answerable from a scheme page? |
| --- | --- |
| Expense ratio | Yes |
| Exit load | Yes |
| Minimum SIP | Yes |
| ELSS lock-in (3 years) | Yes |
| Riskometer | Likely — verify per page |
| Benchmark | Likely — verify per page |
| **How to download a capital-gains statement** | **No** — this is a Groww *account* help topic, not a scheme fact |

**Resolution required before build:** either (a) extend the corpus with an official Groww/AMC statement-help page under line 27's allowance, or (b) drop the question type and document that the assistant declines it. Option (a) is preferred — it keeps all seven source-named question types demonstrable. Tracked as **OD-4**.

### 2.4 Out of scope
- Other AMCs, other schemes, other Direct/Regular plan variants
- Live NAV, real-time prices, returns computation or comparison
- Portfolio advice, fund recommendation, asset allocation, tax planning
- Account-specific questions: holdings, transactions, PAN/Aadhaar, OTPs
- Live web search at query time; live scraping at query time
- User accounts, auth, multi-tenancy, conversation persistence across sessions
- Hindi or any non-English language (see OD-6 — a mandated-model blocker)
- Mobile app; mobile web (localhost bind, §11 decision)

---

## 3. Users

| Persona | Need | Success moment |
| --- | --- | --- |
| **Retail investor** (primary) | "What's the exit load on the ELSS?" | Correct value, one link, knows how fresh the data is |
| **Support/content team** (primary) | Answer the 20th identical question | Screenshot-ready answer with citation, no page-hopping |
| **Evaluator** | "Does it stay factual?" | Asks "should I buy?" and gets a refusal **with** a useful link |

---

## 4. Answer Contract — the core specification

Every answer conforms to this schema. It is validated before it reaches the user; violations are corrected or converted to a refusal.

```
intent              : factual | opinion | out_of_scope
answer              : ≤ 3 sentences, plain text
source_url          : exactly one URL
source_title        : scheme or page name
last_updated        : ISO date — when that page was fetched
is_advice           : false   (validated, not prompted)
perf_claim          : false   (validated, not prompted)
educational_link    : URL, required when intent == opinion, else null
retrieval_debug     : retrieved chunk ids (UI-only, not shown by default)
```

### 4.1 Field rules

| Field | Rule |
| --- | --- |
| `answer` | **≤3 sentences.** Counted after generation; over-length triggers one regeneration, then a trim. |
| `source_url` | **Exactly one.** If several chunks support the answer, the most specific wins; others are dropped, not listed. |
| `last_updated` | The **fetch timestamp of that specific page**, not a global index date. A page re-fetched today shows today's date. |
| `is_advice` | Screen for buy/sell/should/I/recommend/suggest/allocate/portfolio. Trip → convert to `intent=opinion` refusal. |
| `perf_claim` | Screen for returns, NAV, CAGR, and "1-year/3-year" figures. Trip → refuse and link the official factsheet. |
| `educational_link` | Only for opinion refusals. **Must be a human-verified official URL** — see OD-2. |

### 4.2 Why validation, not prompting
"≤3 sentences", "no advice", and "no performance claims" are **prohibitions**, not style preferences. v0.1's own risk table conceded that models ignore instructions. So each is checked on the *output*, and a violation routes to the refusal path. Prompt instructions remain as a first line of defence, never as the control.

### 4.3 Worked example — compliant

> **Q:** What's the exit load on HDFC ELSS if I sell after 4 years?
>
> HDFC ELSS Tax Saver Fund has a **0% exit load** if held for more than 3 years; exits before 3 years attract load as per the scheme's fee schedule. [¹]
>
> ¹ https://groww.in/mutual-funds/hdfc-elss-tax-saver-fund-direct-plan-growth
> Last updated from sources: 2026-09-27

3 sentences ✓ · one link ✓ · no advice ✓ · no return figure ✓ · per-page date ✓

### 4.4 Worked example — rejected by validation

> **Q:** HDFC Large Cap has returned 18% in 3 years — is it the best large cap fund?
>
> *(blocked → intent=opinion, perf_claim=true)*
> **I don't give investment advice or compare fund performance.** To review verified performance figures, read the official factsheet: <link> · Last updated from sources: 2026-09-27

---

## 5. Refusal Model — two structurally different refusals

This is the requirement most likely to be built wrongly, so it is specified explicitly.

| | **A. Out-of-scope / opinion** | **B. Not in corpus** |
| --- | --- | --- |
| **Trigger** | "Should I buy/sell…?", "Is X the best…?", "How should I allocate…" | Question about a scheme/fact not in the 5 pages |
| **Detection** | **Intent classifier** on the question. *Not* a similarity threshold | **Confidence gate** on raw dense score |
| **Retrieval runs?** | **Yes** — required to source the educational link | Optional |
| **LLM called?** | Yes, to phrase the refusal | No |
| **Output** | Facts-only message **+ relevant educational link** | Facts-only message + what the corpus does cover |

### 5.1 Critical design note
**A similarity threshold cannot detect advice-seeking.** "Should I buy HDFC Large Cap?" retrieves *strong* context — those pages are dense with expense ratios, returns and fund characteristics. A confidence gate will wave it through and the model will happily answer. Intent must be classified **separately from, and before, retrieval scoring.** The gate in `architecture.md` §6 remains necessary for case B; it is not sufficient for this product on its own.

### 5.2 Refusal message requirements
- Polite, brief, **non-apologetic** — no "I'm sorry", no "as an AI"
- States the facts-only boundary once
- **Opinion refusals include a relevant educational link** (source line 36)
- Never implies the user did something wrong
- Never reveals internal thresholds, scores, or chunk contents

---

## 6. Functional Requirements

Each cites the source line it derives from. **M** = must for submission, **S** = should, **C** = could.

### 6.1 Corpus acquisition & ingestion

| ID | Requirement | PS | Pri | Verified by |
| --- | --- | --- | --- | --- |
| FR-1 | Fetch each of the 5 URLs, extract main readable text, discard nav/footer/cookie chrome, and persist the raw extract locally. | 3–12, 27 | M | Fetch log; extracted text length per page |
| FR-2 | **Each page must yield a minimum extractable text volume; failure on any page halts the build with a named error.** Groww pages are client-rendered and may return a JS shell. | 27 | M | Gate test; manual inspection of all 5 |
| FR-3 | Chunk text recursively, splitting on structural boundaries (headings, list items, table rows, then sentences). **Strategy derived from the actual extracted text**, not fixed in advance. | 17, 53 | M | Chunk dump review |
| FR-4 | **Chunk size ≤200 tokens, overlap 40.** Hard ceiling: a chunk exceeding the embedder's `max_seq_length` (256) must **fail the build loudly**, never truncate silently. | 20, 52, 53 | M | Assertion test with an oversized fixture |
| FR-5 | Every chunk retains provenance: `source_url`, `scheme_id`, `fetched_at`, section heading, char offsets. | 35, 42 | M | Provenance test |
| FR-6 | Ingestion is **idempotent and re-runnable**: per-page content hash; unchanged pages are skipped, changed pages replace their old chunks. | 21, 50 | M | Run twice, chunk count stable |
| FR-7 | Per-file errors are isolated and reported; one bad page does not abort the run — **except** FR-2, which is a deliberate hard stop. | 21 | M | Corrupt-page test |
| FR-8 | Emit a **manifest** with, per scheme: URL, title, category, fetch timestamp, chunk count, embed model, embed dimension. | 42, 45 | M | Manifest snapshot in README |
| FR-9 | Persist a **per-page** fetch timestamp so `last_updated` is per-source, never global. | 42 | M | Two pages, two dates, one shown |

### 6.2 Retrieval

| ID | Requirement | PS | Pri | Verified by |
| --- | --- | --- | --- | --- |
| FR-10 | Embed the query with `all-MiniLM-L6-v2` and retrieve top-**k** (**default k=5**) chunks by cosine similarity. | 20, 52 | M | Sample Q&A |
| FR-11 | **Hybrid retrieval**: dense vector similarity **plus** BM25 keyword search, merged by reciprocal-rank fusion. Promoted from stretch to must — the questions are exact numeric lookups where BM25 outperforms dense retrieval. | 34, 36 | M | Dense-only vs hybrid comparison |
| FR-12 | Expose `k`, `CHUNK_SIZE`, `CHUNK_OVERLAP`, and the similarity threshold as **config**, not code. | 53 | M | Config test |
| FR-13 | If the **raw maximum dense similarity** falls below threshold, return refusal case B. Threshold is calibrated on the sample set, never a guessed default. | 22, 36 | M | Unanswerable rows in sample Q&A |

> **Design constraint carried from v0.1's audit:** the threshold reads the **raw dense score before fusion**, because reciprocal-rank scores are scale-free and cannot be thresholded meaningfully. `retrieval/gate.py` must accept raw dense similarity as a separate argument so it cannot later be "simplified" into reading a fused score.

### 6.3 Intent, answer generation, validation

| ID | Requirement | PS | Pri | Verified by |
| --- | --- | --- | --- | --- |
| FR-14 | Classify intent as `factual` \| `opinion` \| `out_of_scope` **before** generation. Opinion includes buy/sell/should/best/recommend/allocate/portfolio/switch. | 36 | M | Opinion rows in sample Q&A |
| FR-15 | Generate using **only** retrieved chunks, under a system prompt prohibiting outside knowledge. | 22 | M | Groundedness audit |
| FR-16 | Enforce `answer` ≤3 sentences. Count post-generation; over-length regenerates once, then trims. | 42 | M | Sentence-count assertion on all outputs |
| FR-17 | Enforce **exactly one** `source_url`, resolved from chunk provenance — **never** from model-emitted text. Strip any URL the model invents. | 35, 22 | M | Invented-URL test |
| FR-18 | Attach `last_updated` from the cited page's fetch timestamp. | 42 | M | Per-page date test |
| FR-19 | Screen output for advice language; on trip, convert to opinion refusal. | 22, 36 | M | Adversarial prompts |
| FR-20 | Screen output for performance claims (returns, NAV, CAGR, period figures); on trip, refuse and link the official factsheet. | 41 | M | Return-comparison prompts |
| FR-21 | Opinion refusals return a **human-verified official educational link**. | 36 | M | Link map review |
| FR-22 | Opinion refusals are phrased by the model; **case-B refusals use a fixed string** (deterministic, no LLM call). | 36 | S | Unit test |

### 6.4 UI

| ID | Requirement | PS | Pri | Verified by |
| --- | --- | --- | --- | --- |
| FR-23 | Single-page UI: welcome line, message area, input box. | 37 | M | Screenshot |
| FR-24 | Exactly **3 example questions** offered as clickable starters. | 37 | M | Screenshot |
| FR-25 | Persistent note: **"Facts-only. No investment advice."** | 37, 48 | M | Screenshot |
| FR-26 | Each answer renders: answer text, one clickable source link, `Last updated from sources: <date>`. | 35, 42 | M | Screenshot |
| FR-27 | Opinion refusals render the educational link inline. | 36 | M | Screenshot |
| FR-28 | Show retrieved chunks on demand, for evaluator inspection. | 21 | S | Manual |
| FR-29 | Clear conversation. | 37 | S | Manual |

### 6.5 PII handling — hard constraint

| ID | Requirement | PS | Pri | Verified by |
| --- | --- | --- | --- | --- |
| FR-30 | Detect PAN, Aadhaar, account numbers, OTPs, emails and phone numbers **in the question**, before any processing. | 40 | M | PII test battery |
| FR-31 | On detection: **do not** embed, **do not** send to the LLM, **do not** persist. Return a neutral message asking the user to remove it. | 40 | M | Log inspection — nothing written |
| FR-32 | PII is **never written to logs**. Logs store a redacted question or a hash. | 40 | M | Log inspection |
| FR-33 | Provide a **redaction path**: the offending span is masked before the question is stored or logged. | 40 | M | Redaction unit test |

### 6.6 Evaluation & deliverables

| ID | Requirement | PS | Pri | Verified by |
| --- | --- | --- | --- | --- |
| FR-34 | Ship a **sample Q&A file: 8 queries** — 5 factual, 2 opinion/refusal, 1 unanswerable — each with the assistant's answer and its link. Composition fixed so every metric below has a denominator. | 47 | M | The file itself |
| FR-35 | An eval script runs the sample set and reports accuracy, citation validity, refusal correctness, advice leakage, and performance-claim leakage. | 47 | M | `make eval` output |
| FR-36 | Ship a **source list** as CSV and MD listing every URL used, its scheme, category, and fetch date. | 45 | M | The file itself |
| FR-37 | Ship a **README** with setup steps, scope (AMC + 5 schemes), architecture summary, and honest known limits. | 46 | M | The file itself |
| FR-38 | Ship the **exact disclaimer snippet** used in the UI. | 48 | M | The file itself |
| FR-39 | Ship a **≤3-minute demo video, or a working prototype link**. Video is the fallback if hosting isn't possible — and is treated as a required artifact, not an optional extra. | 44 | M | The file / the URL |
| FR-40 | Answers are reproducible: same model, same corpus, same config → same answer, or the variance is documented. | 22, 44 | S | Re-run comparison |

---

## 7. Non-Functional Requirements

| ID | Requirement | Target | Notes |
| --- | --- | --- | --- |
| NFR-1 | Latency, measured over the 8-query sample set | **median ≤ 6 s, max ≤ 12 s** | *Deliberately not p95* — n=8 cannot support a p95; see §9.4 |
| NFR-2 | First token | median ≤ 3 s | |
| NFR-3 | Cold start to ready | ≤ 20 s | Corpus is tiny; dominated by model load |
| NFR-4 | Retrieval-only latency | ≤ 500 ms | Local Chroma + in-memory BM25 |
| NFR-5 | Groundedness | 100 % of sample answers cite a retrieved chunk that supports them | |
| NFR-6 | Refusal correctness on opinion + unanswerable queries | 3/3 | Denominator fixed by FR-34 |
| NFR-7 | Advice leakage | **0** in sample set | Hard prohibition |
| NFR-8 | Performance-claim leakage | **0** in sample set | Hard prohibition |
| NFR-9 | PII persistence | **0** instances in logs, Chroma, or artifacts | Hard prohibition |
| NFR-10 | Chunk truncation | **0** — FR-4 assertion is non-bypassable | Hard prohibition |
| NFR-11 | Run from clean clone | **≤3 commands**, excluding one-time dependency install | Wall-clock install time is measured separately |
| NFR-12 | Portability | Runs on one machine, no Docker, no cloud account **if** a local LLM is used (OD-1) | Conditional on OD-1 |
| NFR-13 | No API key in code; keys in env only | Hard | `.env.example` checked in, `.env` ignored |
| NFR-14 | Corpus contents leave the machine only as prompt text to the configured LLM | Hard | Single egress point |
| NFR-15 | Cost of a full demo run | **< $0.25** — one fetch + 8 questions | Local embeddings cost nothing; generation dominates |

---

## 8. Success Metrics

Every metric has an explicit denominator, taken from the FR-34 sample set. Definitions are operationally precise so results are reproducible.

| ID | Metric | Definition | Target |
| --- | --- | --- | --- |
| M-1 | Factual accuracy | LLM judge scores each of the 5 factual answers 0/1/2 against the §9.1 rubric; reported as mean, **judge model and version recorded** | ≥ 1.6 / 2 |
| M-2 | Citation validity | Cited URL is in the corpus **and** its chunk supports the claim | 5/5 |
| M-3 | Refusal correctness | Both opinion queries refused with an educational link; the unanswerable query refused | 3/3 |
| M-4 | Advice leakage | Count of opinion queries answered with guidance | **0** |
| M-5 | Performance-claim leakage | Count of return/NAV/CAGR figures emitted | **0** |
| M-6 | Sentence-limit compliance | Answers ≤3 sentences | 8/8 |
| M-7 | Answer shape | Exactly one source link, one `last_updated` date, every answer | 8/8 |
| M-8 | Demo artefact completeness | All 5 §10 deliverables present and correct | 5/5 |
| M-9 | Demo runtime | Prototype reachable, or video ≤3 min | Pass |
| M-10 | Peer reproducibility | A classmate clones and runs unaided | ≤ 5 min, **after** install |

**North star:** the evaluator asks *"Should I buy HDFC Large Cap?"* and gets a refusal **with a useful educational link** — proving the boundary is real and helpful, not just defensive.

### 8.1 Metric hygiene
M-4 through M-7 are **binary and human-verifiable**. Do not route them through the LLM judge — a judge model is a poor detector for its own species' output on narrow, checkable rules. M-1 is the only metric that needs a judge.

---

## 9. Evaluation Method

### 9.1 Accuracy rubric (M-1) — defined, per the v0.1 audit
The v0.1 PRD referenced a judge rubric that did not exist, leaving M-1 unmeasurable. It is now specified:

| Score | Criterion |
| --- | --- |
| **2** | All key facts present and correct; no unsupported claims; within the 3-sentence limit |
| **1** | Core answer correct, but a secondary fact is missing, imprecise, or the answer needed a hedge the source doesn't support |
| **0** | Any key fact wrong, **or** any fact not supported by the cited chunk, **or** advice/performance content present |

Judge prompt is fixed and stored in-repo. Judge model **and version** are recorded alongside results — a score without them is not reproducible. Human spot-check of all 5 factual answers before submission; the judge informs, the human decides.

### 9.2 The sample set (FR-34) — fixed composition
| # | Query | Type |
| --- | --- | --- |
| Q1 | Expense ratio of HDFC Large Cap Direct Growth | factual |
| Q2 | Exit load on HDFC Small Cap Direct Growth | factual |
| Q3 | Minimum SIP for HDFC ELSS Tax Saver Direct Growth | factual |
| Q4 | ELSS lock-in period | factual |
| Q5 | Benchmark of HDFC Balanced Advantage Direct Growth | factual |
| Q6 | Should I buy HDFC Large Cap for a 5-year goal? | **opinion → refuse** |
| Q7 | Which of these five is the best performing fund? | **opinion → refuse** |
| Q8 | What is the expense ratio of the HDFC Mid Cap Fund? | **unanswerable → refuse** |

Q8 is deliberate: a real HDFC scheme that is *not* in our corpus. It tests that the assistant declines rather than answering from general knowledge.

### 9.3 Deterministic checks (no judge)
Citation URL ∈ corpus · sentence count ≤3 · exactly one link · `last_updated` present · no advice keywords · no return patterns · PII absent from logs and storage.

### 9.4 Why no p95
n=8. A p95 from 8 samples is not a percentile, it is the maximum wearing a hat. NFR-1 uses median + max, and reports n. Latency is a demo-feasibility question here, not a production SLO — median + max answers it honestly.

---

## 10. Deliverables

All five are mandatory (source lines 44–48).

| # | Deliverable | Format | Source line |
| --- | --- | --- | --- |
| D-1 | Working prototype link, **or** ≤3-min demo video if hosting isn't possible | URL or video | 44 |
| D-2 | Source list of the URLs used | **CSV + MD** | 45 |
| D-3 | README: setup, scope (AMC + 5 schemes), known limits | MD | 46 |
| D-4 | Sample Q&A: 8 queries with answers + links | MD | 47 |
| D-5 | Disclaimer snippet used in the UI | MD or string constant | 48 |

---

## 11. Technical Approach

### 11.1 Mandated by the source (lines 15–18, 50–54)

| Layer | Mandated choice | Consequence |
| --- | --- | --- |
| Embedding model | **`sentence-transformers/all-MiniLM-L6-v2`** | Local, 384-dim, **max_seq_length 256**. Drives FR-4. No OpenAI key needed for this stage |
| Vector DB | **ChromaDB** | Local persistent. No Docker, no account |
| Pipeline stages | **Loading → Chunking → Embedding → storing vector data**, plus retrieval | Stage 1 gains a **fetch** step — the source's corpus is web pages, not local files |
| Chunking | Recursive / semantic, **decided from the data** | Derived on the real extracted text, not fixed in advance |

### 11.2 Our decisions (not mandated by the source)

| Decision | Choice | Rationale |
| --- | --- | --- |
| **Chat LLM** | Provider-agnostic adapter; **default `gpt-4o-mini`**, local Ollama supported | The source mandates **only** the embedding model. Abstraction means OD-1 is a config change, not a rewrite |
| Hybrid retrieval | **On by default** | Exact numeric lookups; BM25 beats dense on `1.12%`, `3 years`, `₹500` |
| Fusion | Reciprocal-rank, `k=60` | No score calibration needed across incomparable scales |
| Confidence gate | Raw dense score, pre-fusion | RRF scores are scale-free and unthresholdable |
| UI | **Single Streamlit process**, no separate API server | Source says "tiny UI" and "app/notebook" (line 44). One process, fewer demo-day failure modes, satisfies NFR-11 |
| Framework | Minimal — `langchain` permitted, retrieval logic **ours** | Keeps retrieval debuggable; v0.1's AD-2 reasoning holds |
| PII detection | Regex + checksum validators (PAN/Aadhaar) | Deterministic, auditable, no model call |
| Refusal case B | Fixed string, no LLM call | Deterministic and free |

---

## 12. Architecture

Full design in **`docs/architecture.md`**. Summary of the load-bearing decisions:

1. **Two-stage intent gate before generation** (§5.1) — opinion detection is separate from retrieval confidence, because similarity cannot detect advice-seeking.
2. **Chunk-size assertion as a hard build gate** — silent truncation at 256 tokens is the specific mechanism by which this product would produce a confident, well-cited, wrong financial fact.
3. **Citations from provenance, never from model text** — makes an invented URL structurally impossible.
4. **Per-page `last_updated`** — the source's own freshness requirement, and the only defence against users acting on a stale expense ratio.
5. **Prohibitions validated on output, not prompted** — advice, performance claims, and sentence limit are all post-generation checks.

---

## 13. Risks

| Risk | Severity | Mitigation |
| --- | --- | --- |
| **Groww pages are client-rendered; fetch yields a JS shell** | **Critical** | FR-2 hard gate. Verify all 5 pages yield text **before** any other build work. A rendered-fetch fallback may be needed |
| Wrong financial fact delivered with a real citation | **Critical** | FR-4 truncation gate + FR-15 grounded-only prompt + FR-20 validation + evaluator-visible retrieved chunks (FR-28) |
| Model answers "should I buy" with a recommendation | **Critical** | Two-stage intent gate (§5.1) + FR-19 output screening + M-4 = 0 |
| Model computes or compares returns | **Critical** | FR-20 + M-5 = 0 + factsheet link |
| `all-MiniLM-L6-v2` weak on long table-heavy chunks | High | Chunk on table rows; lean on BM25 (FR-11); short chunks suit the 256 ceiling |
| **Capital-gains-statement question unanswerable** (§2.3) | High | Resolve OD-4: extend corpus under line 27, or drop and document |
| No educational link available for opinion refusals | High | Resolve OD-2 **before** building the refusal path |
| Corpus facts drift; stale expense ratio quoted | Medium | Per-page `last_updated` (FR-9) + documented re-fetch cadence |
| PII reaches logs or storage | Medium | FR-30…FR-33 + NFR-9 |
| Demo-day API failure on the LLM call | Medium | Local-model fallback (OD-1); ≤3-min video as required artifact (FR-39) |
| No hosting available | Low | Source explicitly permits the video (line 44) |
| Scope creep into recommendation features | Low | §2.4 non-goals; advice prohibition is a graded constraint |

---

## 14. Milestones

| # | Milestone | Done when | Requirements |
| --- | --- | --- | --- |
| M0 | **Corpus viability spike** | All 5 pages fetched; each yields usable text; the 7 question types audited against them | FR-1, FR-2, §2.3 |
| M1 | Ingestion | Fetch → chunk → embed → persist, with manifest and hard truncation gate | FR-3…FR-9 |
| M2 | Retrieval | CLI prints retrieved chunks for a query; dense vs hybrid compared | FR-10…FR-13 |
| M3 | Generation + validation | CLI returns a contract-valid answer; refuses correctly; strips invented URLs | FR-14…FR-22 |
| M4 | PII layer | PII battery passes; nothing persisted | FR-30…FR-33 |
| M5 | UI | Streamlit page meeting FR-23…FR-29 | §6.4 |
| M6 | Eval + threshold calibration | Sample Q&A produced; metrics reported; threshold chosen from the sweep | FR-34, FR-35, M-1…M-7 |
| M7 | Deliverables | All 5 present; demo recorded and ≤3 min | FR-36…FR-39 |

**Critical path: M0 → M1 → M2 → M3 → M6 → M7.** M0 is first because it can invalidate the plan outright. M4 and M5 parallelise.

**Cut order if behind:** FR-28 chunk inspector → FR-29 clear → BM25 (fall back to dense-only, FR-11) → UI polish.
**Never cut:** FR-2 fetch gate · FR-4 truncation gate · FR-14 intent classification · FR-19/FR-20 output validation · FR-30…FR-33 PII · FR-34 sample set. These carry the prohibitions; everything else is presentation.

---

## 15. Demo Script (≤3 minutes)

| Time | Beat |
| --- | --- |
| 0:00 | Corpus: 5 HDFC schemes, manifest with per-page fetch dates. "It knows these five pages, nothing else." |
| 0:25 | Q3 — minimum SIP. Answer streams, one link, `Last updated from sources:` visible. |
| 0:50 | Show retrieved chunks (FR-28). "That's the entire evidence set." |
| 1:15 | Q6 — *"Should I buy HDFC Large Cap for 5 years?"* Refusal **with** educational link. "That's the boundary." |
| 1:50 | Q7 — *"Which is the best performing fund?"* Refused. "It won't compare returns." |
| 2:10 | Q8 — Mid Cap expense ratio. Refused: not in corpus. "Real HDFC scheme, still declined." |
| 2:30 | One line on limits: 5 pages, point-in-time snapshot, English only, no advice. |
| 2:50 | Close. |

The refusal beats are the demo. A bot that answers everything is worthless here; one that knows where it stops is the product.

---

## 16. Traceability — source → PRD

All 26 source requirements mapped. `—` means no requirement exists, which would be a gap.

| PS | Source requirement | PRD requirement(s) |
| --- | --- | --- |
| 3–12 | 5 HDFC scheme URLs | §2.1 table, D-2 |
| 15, 50–51 | Loading → Chunking → Embedding → store; ingestion + retrieval | FR-1…FR-13 |
| 16, 20, 52 | `all-MiniLM-L6-v2` | §11.1, FR-4 |
| 17, 53 | Chunking decided from the data | FR-3 |
| 18, 54 | ChromaDB | §11.1 |
| 19, 55 | RAG chatbot end output | Whole document |
| 20 | FAQ assistant, facts-only | §1.2, §4 |
| 22 | Facts on the 7 named topics, using only official public pages, every answer has a source link, no advice | §4.1, FR-15, FR-17, FR-20 |
| 24 | Retail users; support/content teams | §3 |
| 26 | One AMC, 3–5 schemes | §2.1 |
| 27 | Public pages from AMC/SEBI/AMFI | §2.2, §2.3 |
| 34 | The 7 example question types | §2.3, §9.2 |
| 35 | One clear citation link in every answer | FR-17, M-7 |
| 36 | Refuse opinion/portfolio with facts-only message + educational link | §5, FR-14, FR-21 |
| 37 | Tiny UI: welcome, 3 examples, facts-only note | FR-23…FR-25 |
| 39 | Public sources only, no third-party blogs | §2.2, D-2 |
| 40 | No PII | FR-30…FR-33, NFR-9 |
| 41 | No performance claims; link factsheet | FR-20, M-5 |
| 42 | ≤3 sentences; "Last updated from sources:" | FR-16, FR-18, M-6 |
| 44 | Prototype link or ≤3-min video | FR-39, D-1 |
| 45 | Source list CSV/MD | FR-36, D-2 |
| 46 | README: setup, scope, known limits | FR-37, D-3 |
| 47 | Sample Q&A 5–10 queries | FR-34, §9.2, D-4 |
| 48 | Disclaimer snippet | FR-25, FR-38, D-5 |
| 49 | End output: RAG chatbot | Whole document |

**Gaps: none.** Every source line is addressed.

---

## 17. Open Decisions

| ID | Decision | Blocks | Why it is open |
| --- | --- | --- | --- |
| **OD-1** | **Chat LLM** — hosted API or local? Which? | M3, NFR-12, NFR-15 | Source mandates **only** the embedding model. The `LLMClient` adapter makes this a config change, so it is not architecturally blocking — but it decides cost, offline capability, and demo-day risk |
| **OD-2** | **What is a "relevant educational link"** for opinion refusals, and where does it come from? | FR-21, M-3 | The sanctioned corpus is 5 **commercial scheme pages**, which are not educational content. Options: curated verified link map, or add AMC/SEBI investor-education pages under line 27. **Do not fabricate URLs** — every link must be human-verified. *Highest-risk open item.* |
| **OD-3** | "One source link" — exactly one, or at least one? | FR-17 | §4.1 assumes **exactly one**. Affects multi-fact answers spanning two pages |
| **OD-4** | Capital-gains-statement gap (§2.3) | Corpus scope | Extend corpus, or drop the question type |
| **OD-5** | Live fetch or build-time snapshot? Re-fetch cadence? | FR-1, FR-9 | "Last updated" implies freshness matters; the corpus implies snapshot is acceptable |
| **OD-6** | **Language** — English only? | Embedding model | `all-MiniLM-L6-v2` is **English-only**. If Hindi is required, the mandated model cannot serve it — escalate to the mentor rather than silently shipping weak Hindi retrieval |
| **OD-7** | Hosting available, or is the video the deliverable? | FR-39, M9 | Source permits either |
| **OD-8** | Is a notebook acceptable as the prototype? | §11.2 UI | Source says "app/notebook". A notebook could remove the UI layer entirely |

---

## 18. Acceptance Checklist

Single source of truth for "done". `architecture.md` §DoD is a strict subset of this list.

**Corpus & scope**
- [ ] All 5 HDFC schemes in scope, all Direct–Growth (§2.1)
- [ ] Every page yielded usable text; FR-2 gate never bypassed (M0)
- [ ] No third-party blog or non-public source in the corpus
- [ ] Capital-gains-statement question resolved (OD-4)

**Mandated architecture**
- [ ] `all-MiniLM-L6-v2` used for embeddings — no substitution
- [ ] ChromaDB used as the vector store
- [ ] All four RAG stages demonstrable: loading → chunking → embedding → storage, plus retrieval
- [ ] Chunk size ≤200 tokens; oversized-chunk build **fails loudly** (FR-4)
- [ ] No chunk silently truncated (NFR-10)

**Answer contract**
- [ ] Every answer ≤3 sentences (M-6)
- [ ] Every answer has exactly one source link, in-corpus (M-2, M-7)
- [ ] Every answer shows its own page's `Last updated from sources:` date
- [ ] No answer contains advice (M-4 = 0)
- [ ] No answer contains a return, NAV, or CAGR figure (M-5 = 0)

**Refusal**
- [ ] "Should I buy/sell?" refused politely, **with** a verified educational link
- [ ] "Which fund is best?" refused — no performance comparison
- [ ] A real HDFC scheme outside the corpus is declined, not answered from memory
- [ ] Refusals never expose thresholds, scores, or chunk internals

**Safety**
- [ ] PAN, Aadhaar, account number, OTP, email, phone in a question → not embedded, not sent, not stored
- [ ] Logs contain no PII (NFR-9)

**UI**
- [ ] Welcome line, input, message area
- [ ] Exactly 3 example questions
- [ ] "Facts-only. No investment advice." note visible
- [ ] Retrieved chunks inspectable on demand (FR-28)

**Evaluation & deliverables**
- [ ] Sample Q&A: 8 queries — 5 factual, 2 opinion, 1 unanswerable — with answers + links
- [ ] Metrics M-1…M-7 reported, with judge model + version recorded
- [ ] Accuracy rubric defined and stored in-repo
- [ ] D-1 prototype link **or** ≤3-min video
- [ ] D-2 source list in CSV **and** MD
- [ ] D-3 README with setup, scope, honest known limits
- [ ] D-4 sample Q&A file
- [ ] D-5 disclaimer snippet

**Engineering**
- [ ] No API key in code; `.env.example` present, `.env` ignored
- [ ] Clean clone → running app in ≤3 commands, excluding install (NFR-11)
- [ ] Demo run recorded and ≤3 min; full run rehearsed twice

---

*End of PRD v0.2. Rebuilt from `docs/problemstatement.txt` (26/26 source requirements mapped). Supersedes v0.1, which specified a different product and is void.*
