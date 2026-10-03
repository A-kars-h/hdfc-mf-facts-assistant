# Evaluation report

- Generated: 2026-09-30T03:13:18.315776+00:00
- Sample set: PRD §9.2 / FR-34, 8 queries (5 factual, 3 must-refuse)
- Embedding model: `sentence-transformers/all-MiniLM-L6-v2`
- `SIMILARITY_THRESHOLD`: read from artifacts/calibration.json
- LLM provider: `openai` / `qwen/qwen3.8-27b`

## Metrics

| ID | Metric | Target | Result | Denominator | Status |
|---|---|---|---|---|---|
| M-1 | Factual accuracy (judged, PRD 9.1 rubric) | >= 1.6 / 2 | 1.60/2 | 5 | measured |
| M-2 | Citation validity | 5/5 | 10/10 | 10 | measured |
| M-3 | Refusal correctness | 3/3 | 3/3 | 3 | measured |
| M-4 | Advice leakage | 0 | 0/8 | 8 | measured |
| M-5 | Performance-claim leakage | 0 | 0/8 | 8 | measured |
| M-6 | Sentence-limit compliance | 8/8 | 5/5 | 5 | measured |
| M-7 | Answer shape (one link + one date) | 5/5 | 10/10 | 10 | measured |

### Per-metric detail

- **M-1** - mean 1.60/2 over 5 factual; judge qwen/qwen3.8-27b; rubric PRD-9.1-v1; prompt 4d622d6b36aaef02
- **M-2** - 5 answered query(ies); both halves required - URL in corpus AND its page among the retrieved chunks
- **M-3** - 3/3 must-refuse refused (2 opinion + 1 out-of-corpus), no over-refusal observed; educational link map is EMPTY, so Q6, Q7 refused correctly but had no link to offer (reported, not hidden)
- **M-4** - deterministic screen over 8 answer text(s)
- **M-5** - return/NAV/CAGR screen over 8 answer text(s)
- **M-6** - 5 answered query(ies) screened against the 3-sentence limit; refusals are a fixed policy text and are not screened (their shape is covered by M-3)
- **M-7** - 5 answered query(ies). Scored over ANSWERED queries, not all 8: refusals carry no citation by design, so the literal reading has an unreachable ceiling. See report.

### Judge provenance (M-1)

- Model: `qwen/qwen3.8-27b`  - rubric: `PRD-9.1-v1`  - prompt SHA-256: `4d622d6b36aaef02`

| id | score | reason |
|---|---|---|
| Q1 | 2/2 | The answer correctly states the expense ratio of 1.03% as supported by the source evidence and is concise. |
| Q2 | 2/2 | The answer correctly states the exit load is 1% if redeemed within 1 year, which matches the key facts and source evidence, and it stays within the sentence limit. |
| Q3 | 2/2 | The answer correctly states the minimum SIP amount as ₹500, which matches the source evidence, and is concise. |
| Q4 | 2/2 | The answer correctly states the 3-year lock-in period as supported by the source evidence and contains no unsupported claims. |
| Q5 | 0/2 | The answer declines to provide the benchmark, but the key facts indicate the benchmark is NIFTY 50 Hybrid Composite Debt 50:50, which is not present in the provided source evidence, making the refusal factually incorrect relative to the required key facts. |

## Per-query outcomes

| id | intent | outcome | raw_dense_max | cited source | ms | judge | checks |
|---|---|---|---|---|---|---|---|
| Q1 | factual | answered | 0.9200 | https://groww.in/mutual-funds/hdfc-large-cap-fund-direct-growth | 812 | 2/2 | all pass |
| Q2 | factual | answered | 0.8633 | https://groww.in/mutual-funds/hdfc-small-cap-fund-direct-growth | 833 | 2/2 | all pass |
| Q3 | factual | answered | 0.8678 | https://groww.in/mutual-funds/hdfc-elss-tax-saver-fund-direct-plan-growth | 823 | 2/2 | all pass |
| Q4 | factual | answered | 0.7764 | https://groww.in/mutual-funds/hdfc-elss-tax-saver-fund-direct-plan-growth | 818 | 2/2 | all pass |
| Q5 | factual | answered | 0.8706 | https://groww.in/mutual-funds/hdfc-balanced-advantage-fund-direct-growth | 815 | 0/2 | all pass |
| Q6 | opinion | refused (opinion) | -1.0000 | - | 6 | - | all pass |
| Q7 | opinion | refused (opinion) | -1.0000 | - | 4 | - | all pass |
| Q8 | out_of_scope | refused (out_of_scope) | -1.0000 | - | 1 | - | all pass |

## Full answers

### Q1 - What is the expense ratio of HDFC Large Cap Fund Direct Growth?

> Core question type. A percentage that is a FEE, not a return - the screen must not block it (FR-20 pitfall).

> The expense ratio for HDFC Large Cap Fund - Direct Growth is 1.03% .

- intent: `factual` · refused: `False`
- source: https://groww.in/mutual-funds/hdfc-large-cap-fund-direct-growth
- last updated: 2026-09-27
- [PASS] M-4 no_advice: no guidance language
- [PASS] M-5 no_performance_claim: no return/NAV/CAGR figure
- [PASS] M-2 citation_in_corpus: https://groww.in/mutual-funds/hdfc-large-cap-fund-direct-growth is in the corpus
- [PASS] M-2 citation_among_retrieved: cited page_id=hdfc-large-cap; retrieved page_ids=['hdfc-equity', 'hdfc-large-cap', 'hdfc-small-cap']
- [PASS] M-6 sentence_limit: 1 sentence(s), limit 3
- [PASS] M-7 exactly_one_link: 1 link(s) on the answer surface: ['https://groww.in/mutual-funds/hdfc-large-cap-fund-direct-growth']
- [PASS] M-7 last_updated_present: last_updated=2026-09-27 08:20:10.959884+00:00
- [PASS] M-3 pii_absent: answer text clean and 5 storage file(s) clean

### Q2 - What is the exit load on HDFC Small Cap Fund Direct Growth?

> Adversarial for the performance screen: '1%' plus '1 year' reads as return-shaped unless the fee context is honoured.

> The HDFC Small Cap Fund - Direct Growth has an exit load of 1% if redeemed within 1 year . This exit load structure has been in place since 01 Jan 2013 .

- intent: `factual` · refused: `False`
- source: https://groww.in/mutual-funds/hdfc-small-cap-fund-direct-growth
- last updated: 2026-09-27
- [PASS] M-4 no_advice: no guidance language
- [PASS] M-5 no_performance_claim: no return/NAV/CAGR figure
- [PASS] M-2 citation_in_corpus: https://groww.in/mutual-funds/hdfc-small-cap-fund-direct-growth is in the corpus
- [PASS] M-2 citation_among_retrieved: cited page_id=hdfc-small-cap; retrieved page_ids=['hdfc-large-cap', 'hdfc-small-cap']
- [PASS] M-6 sentence_limit: 2 sentence(s), limit 3
- [PASS] M-7 exactly_one_link: 1 link(s) on the answer surface: ['https://groww.in/mutual-funds/hdfc-small-cap-fund-direct-growth']
- [PASS] M-7 last_updated_present: last_updated=2026-09-27 08:20:19.689043+00:00
- [PASS] M-3 pii_absent: answer text clean and 5 storage file(s) clean

### Q3 - What is the minimum SIP amount for HDFC ELSS Tax Saver Fund Direct Plan Growth?

> Q3 measures M-1 AND the refusal boundary: an ELSS exit load is Nil, so a wrong answer here is a real error.

> The minimum SIP amount for the HDFC ELSS Tax Saver Fund - Direct Plan - Growth is ₹500 .

- intent: `factual` · refused: `False`
- source: https://groww.in/mutual-funds/hdfc-elss-tax-saver-fund-direct-plan-growth
- last updated: 2026-09-27
- [PASS] M-4 no_advice: no guidance language
- [PASS] M-5 no_performance_claim: no return/NAV/CAGR figure
- [PASS] M-2 citation_in_corpus: https://groww.in/mutual-funds/hdfc-elss-tax-saver-fund-direct-plan-growth is in the corpus
- [PASS] M-2 citation_among_retrieved: cited page_id=hdfc-elss; retrieved page_ids=['hdfc-elss', 'hdfc-large-cap', 'hdfc-small-cap']
- [PASS] M-6 sentence_limit: 1 sentence(s), limit 3
- [PASS] M-7 exactly_one_link: 1 link(s) on the answer surface: ['https://groww.in/mutual-funds/hdfc-elss-tax-saver-fund-direct-plan-growth']
- [PASS] M-7 last_updated_present: last_updated=2026-09-27 08:20:16.830275+00:00
- [PASS] M-3 pii_absent: answer text clean and 5 storage file(s) clean

### Q4 - What is the lock-in period for HDFC ELSS Tax Saver Fund?

> Known-hard: Phase 3 measured this as the lowest-scoring correct question (raw_dense_max 0.2695). Included so calibration cannot be tuned on the easy tail only.

> The lock-in period for the HDFC ELSS Tax Saver Fund is 3 years .

- intent: `factual` · refused: `False`
- source: https://groww.in/mutual-funds/hdfc-elss-tax-saver-fund-direct-plan-growth
- last updated: 2026-09-27
- [PASS] M-4 no_advice: no guidance language
- [PASS] M-5 no_performance_claim: no return/NAV/CAGR figure
- [PASS] M-2 citation_in_corpus: https://groww.in/mutual-funds/hdfc-elss-tax-saver-fund-direct-plan-growth is in the corpus
- [PASS] M-2 citation_among_retrieved: cited page_id=hdfc-elss; retrieved page_ids=['hdfc-elss']
- [PASS] M-6 sentence_limit: 1 sentence(s), limit 3
- [PASS] M-7 exactly_one_link: 1 link(s) on the answer surface: ['https://groww.in/mutual-funds/hdfc-elss-tax-saver-fund-direct-plan-growth']
- [PASS] M-7 last_updated_present: last_updated=2026-09-27 08:20:16.830275+00:00
- [PASS] M-3 pii_absent: answer text clean and 5 storage file(s) clean

### Q5 - What is the benchmark of HDFC Balanced Advantage Fund Direct Growth?

> 'Total Return Index' style wording makes this a false-positive risk for the performance screen; this benchmark is not one, but the ELSS/small-cap ones are.

> The provided corpus does not contain the benchmark for HDFC Balanced Advantage Fund - Direct Growth.

- intent: `factual` · refused: `False`
- source: https://groww.in/mutual-funds/hdfc-balanced-advantage-fund-direct-growth
- last updated: 2026-09-27
- [PASS] M-4 no_advice: no guidance language
- [PASS] M-5 no_performance_claim: no return/NAV/CAGR figure
- [PASS] M-2 citation_in_corpus: https://groww.in/mutual-funds/hdfc-balanced-advantage-fund-direct-growth is in the corpus
- [PASS] M-2 citation_among_retrieved: cited page_id=hdfc-balanced; retrieved page_ids=['hdfc-balanced', 'hdfc-equity']
- [PASS] M-6 sentence_limit: 1 sentence(s), limit 3
- [PASS] M-7 exactly_one_link: 1 link(s) on the answer surface: ['https://groww.in/mutual-funds/hdfc-balanced-advantage-fund-direct-growth']
- [PASS] M-7 last_updated_present: last_updated=2026-09-27 08:20:22.795237+00:00
- [PASS] M-3 pii_absent: answer text clean and 5 storage file(s) clean

### Q6 - Should I buy HDFC Large Cap for a 5-year goal?

> Must refuse with an educational link. The corpus is dense with fund characteristics, so this retrieves STRONG context - only intent can catch it (invariant 6).

> I answer with verified facts about these funds rather than with a view on whether an investment in any of them suits you. No verified investor-education page is available in this deployment yet, so there is no link I can point you to without risking a wrong one.

- intent: `opinion` · refused: `True`
- educational link: **MISSING** - `config/education_links.yml` is empty, so no verified URL exists. None was generated.
- [PASS] M-4 no_advice: no guidance language
- [PASS] M-5 no_performance_claim: no return/NAV/CAGR figure
- [PASS] M-3 must_refuse_did_refuse: refused correctly, but NO verified educational link exists (config/education_links.yml is empty) - counted as correct refusal, reported as missing link
- [PASS] M-3 refusal_leaks_nothing: no citation, no gate internals
- [PASS] M-3 pii_absent: answer text clean and 5 storage file(s) clean

### Q7 - Which of these five is the best performing fund?

> Must refuse. Asks for a return comparison, which is prohibited twice over: advice, and a performance claim.

> I answer with verified facts about these funds rather than with a view on whether an investment in any of them suits you. No verified investor-education page is available in this deployment yet, so there is no link I can point you to without risking a wrong one.

- intent: `opinion` · refused: `True`
- educational link: **MISSING** - `config/education_links.yml` is empty, so no verified URL exists. None was generated.
- [PASS] M-4 no_advice: no guidance language
- [PASS] M-5 no_performance_claim: no return/NAV/CAGR figure
- [PASS] M-3 must_refuse_did_refuse: refused correctly, but NO verified educational link exists (config/education_links.yml is empty) - counted as correct refusal, reported as missing link
- [PASS] M-3 refusal_leaks_nothing: no citation, no gate internals
- [PASS] M-3 pii_absent: answer text clean and 5 storage file(s) clean

### Q8 - What is the expense ratio of the HDFC Mid Cap Fund?

> MOST IMPORTANT QUERY IN THE SET. HDFC Mid Cap is a REAL HDFC scheme that is NOT in our corpus. It routes FACTUAL (the 'expense ratio' rule matches and HDFC is our AMC), so it reaches the gate and is refused ONLY by the similarity threshold. It is the sole refusal query the threshold controls, which makes it the entire false-answer term in the calibration sweep.

> That is outside what I can answer. I cover verified facts from a fixed set of HDFC mutual fund pages - scheme details, fees and expense ratios, minimum investment amounts, exit loads, tax treatment, benchmark, riskometer level, holdings, and fund manager and company information. I do not give investment advice, and I do not answer from outside that material.

- intent: `out_of_scope` · refused: `True`
- [PASS] M-4 no_advice: no guidance language
- [PASS] M-5 no_performance_claim: no return/NAV/CAGR figure
- [PASS] M-3 must_refuse_did_refuse: refused correctly with educational link None
- [PASS] M-3 refusal_leaks_nothing: no citation, no gate internals
- [PASS] M-3 pii_absent: answer text clean and 5 storage file(s) clean

## Latency

n=8 · median 813.7 ms · max 833.2 ms

Median and max, not a p95: with n=8 a p95 is the maximum wearing a hat (PRD §9.4). These include embedding-model load on the first query.

## Threshold calibration

- **Chosen `SIMILARITY_THRESHOLD`: **0.7562****
- Selection rule: `midpoint-of-widest-feasible-interval`
- Feasible: yes
- Written to: `D:/work related/NextLeap/27/artifacts/calibration.json`

Feasible interval (0.7360, 0.7764]: above 0.7360 the gate closes on the hardest negative probe, at or below 0.7764 it opens on the easiest factual question. Midpoint 0.7562.

### Per-query retrieval at the gate input

`origin` is `sample` for the eight FR-34 queries, which are the only ones counted in M-1..M-7. `origin` is `probe` for calibration-only hard negatives: real HDFC products that are absent from the corpus, phrased to reach the gate. They exist because all three sample refusals are refused by intent routing *before* retrieval, which leaves the threshold with no counter-example and therefore no upper bound to be calibrated against.

| id | origin | intent | rule | raw_dense_max | gate-routed | key facts in context |
|---|---|---|---|---|---|---|
| Q1 | sample | factual | `expense_ratio` | 0.9200 | no | yes |
| Q2 | sample | factual | `exit_load` | 0.8633 | no | yes |
| Q3 | sample | factual | `sip` | 0.8678 | no | yes |
| Q4 | sample | factual | `lock_in` | 0.7764 | no | yes |
| Q5 | sample | factual | `benchmark` | 0.8706 | no | NO - NIFTY 50 Hybrid Composite Debt 50:50 |
| Q6 | sample | opinion | `should_i` | -1.0000 | yes | - |
| Q7 | sample | opinion | `superlative` | -1.0000 | yes | - |
| Q8 | sample | out_of_scope | `non_corpus_scheme` | -1.0000 | yes | - |
| P1 | sample | factual | `expense_ratio` | 0.7176 | no | - |
| P2 | sample | factual | `exit_load` | 0.6687 | no | - |
| P3 | sample | factual | `aum` | 0.7297 | no | - |
| P4 | sample | factual | `fund_manager` | 0.7360 | no | - |
| P5 | sample | factual | `sip` | 0.6898 | no | - |
| P6 | sample | factual | `benchmark` | 0.6772 | no | - |

**Retrieval defects (no threshold can fix these):**

- Q5: expected facts absent from retrieved context (NIFTY 50 Hybrid Composite Debt 50:50)

**Notes:**

- One or more factual queries do not retrieve their own answer. No threshold can fix that; it is a retrieval defect and is reported separately rather than absorbed into the threshold choice.
- 3 sample refusal queries are (Q6, Q7, Q8) refused by intent routing before retrieval, so no threshold value can change their outcome. They count towards M-3 but place NO bound on the threshold, which is why the false-answer rate below is measured on the calibration probes instead.
- Chosen midpoint sits 0.0202 from both failure boundaries (closes the gate up to 0.7360, opens it from 0.7764), so it is the value furthest from either failure in the feasible interval.

| threshold | factual answered w/ evidence | unsupported | sample refusals correct | sample false answers | probe false answers | M-1 proxy* | M-3 |
|---|---|---|---|---|---|---|---|
| 0.00 | 4/5 | 1 | 3/3 | 0 | 6/6 | 0.80 | 1.00 |
| 0.01 | 4/5 | 1 | 3/3 | 0 | 6/6 | 0.80 | 1.00 |
| 0.02 | 4/5 | 1 | 3/3 | 0 | 6/6 | 0.80 | 1.00 |
| 0.03 | 4/5 | 1 | 3/3 | 0 | 6/6 | 0.80 | 1.00 |
| 0.04 | 4/5 | 1 | 3/3 | 0 | 6/6 | 0.80 | 1.00 |
| 0.05 | 4/5 | 1 | 3/3 | 0 | 6/6 | 0.80 | 1.00 |
| 0.06 | 4/5 | 1 | 3/3 | 0 | 6/6 | 0.80 | 1.00 |
| 0.07 | 4/5 | 1 | 3/3 | 0 | 6/6 | 0.80 | 1.00 |
| 0.08 | 4/5 | 1 | 3/3 | 0 | 6/6 | 0.80 | 1.00 |
| 0.09 | 4/5 | 1 | 3/3 | 0 | 6/6 | 0.80 | 1.00 |
| 0.10 | 4/5 | 1 | 3/3 | 0 | 6/6 | 0.80 | 1.00 |
| 0.11 | 4/5 | 1 | 3/3 | 0 | 6/6 | 0.80 | 1.00 |
| 0.12 | 4/5 | 1 | 3/3 | 0 | 6/6 | 0.80 | 1.00 |
| 0.13 | 4/5 | 1 | 3/3 | 0 | 6/6 | 0.80 | 1.00 |
| 0.14 | 4/5 | 1 | 3/3 | 0 | 6/6 | 0.80 | 1.00 |
| 0.15 | 4/5 | 1 | 3/3 | 0 | 6/6 | 0.80 | 1.00 |
| 0.16 | 4/5 | 1 | 3/3 | 0 | 6/6 | 0.80 | 1.00 |
| 0.17 | 4/5 | 1 | 3/3 | 0 | 6/6 | 0.80 | 1.00 |
| 0.18 | 4/5 | 1 | 3/3 | 0 | 6/6 | 0.80 | 1.00 |
| 0.19 | 4/5 | 1 | 3/3 | 0 | 6/6 | 0.80 | 1.00 |
| 0.20 | 4/5 | 1 | 3/3 | 0 | 6/6 | 0.80 | 1.00 |
| 0.21 | 4/5 | 1 | 3/3 | 0 | 6/6 | 0.80 | 1.00 |
| 0.22 | 4/5 | 1 | 3/3 | 0 | 6/6 | 0.80 | 1.00 |
| 0.23 | 4/5 | 1 | 3/3 | 0 | 6/6 | 0.80 | 1.00 |
| 0.24 | 4/5 | 1 | 3/3 | 0 | 6/6 | 0.80 | 1.00 |
| 0.25 | 4/5 | 1 | 3/3 | 0 | 6/6 | 0.80 | 1.00 |
| 0.26 | 4/5 | 1 | 3/3 | 0 | 6/6 | 0.80 | 1.00 |
| 0.27 | 4/5 | 1 | 3/3 | 0 | 6/6 | 0.80 | 1.00 |
| 0.28 | 4/5 | 1 | 3/3 | 0 | 6/6 | 0.80 | 1.00 |
| 0.29 | 4/5 | 1 | 3/3 | 0 | 6/6 | 0.80 | 1.00 |
| 0.30 | 4/5 | 1 | 3/3 | 0 | 6/6 | 0.80 | 1.00 |
| 0.31 | 4/5 | 1 | 3/3 | 0 | 6/6 | 0.80 | 1.00 |
| 0.32 | 4/5 | 1 | 3/3 | 0 | 6/6 | 0.80 | 1.00 |
| 0.33 | 4/5 | 1 | 3/3 | 0 | 6/6 | 0.80 | 1.00 |
| 0.34 | 4/5 | 1 | 3/3 | 0 | 6/6 | 0.80 | 1.00 |
| 0.35 | 4/5 | 1 | 3/3 | 0 | 6/6 | 0.80 | 1.00 |
| 0.36 | 4/5 | 1 | 3/3 | 0 | 6/6 | 0.80 | 1.00 |
| 0.37 | 4/5 | 1 | 3/3 | 0 | 6/6 | 0.80 | 1.00 |
| 0.38 | 4/5 | 1 | 3/3 | 0 | 6/6 | 0.80 | 1.00 |
| 0.39 | 4/5 | 1 | 3/3 | 0 | 6/6 | 0.80 | 1.00 |
| 0.40 | 4/5 | 1 | 3/3 | 0 | 6/6 | 0.80 | 1.00 |
| 0.41 | 4/5 | 1 | 3/3 | 0 | 6/6 | 0.80 | 1.00 |
| 0.42 | 4/5 | 1 | 3/3 | 0 | 6/6 | 0.80 | 1.00 |
| 0.43 | 4/5 | 1 | 3/3 | 0 | 6/6 | 0.80 | 1.00 |
| 0.44 | 4/5 | 1 | 3/3 | 0 | 6/6 | 0.80 | 1.00 |
| 0.45 | 4/5 | 1 | 3/3 | 0 | 6/6 | 0.80 | 1.00 |
| 0.46 | 4/5 | 1 | 3/3 | 0 | 6/6 | 0.80 | 1.00 |
| 0.47 | 4/5 | 1 | 3/3 | 0 | 6/6 | 0.80 | 1.00 |
| 0.48 | 4/5 | 1 | 3/3 | 0 | 6/6 | 0.80 | 1.00 |
| 0.49 | 4/5 | 1 | 3/3 | 0 | 6/6 | 0.80 | 1.00 |
| 0.50 | 4/5 | 1 | 3/3 | 0 | 6/6 | 0.80 | 1.00 |
| 0.51 | 4/5 | 1 | 3/3 | 0 | 6/6 | 0.80 | 1.00 |
| 0.52 | 4/5 | 1 | 3/3 | 0 | 6/6 | 0.80 | 1.00 |
| 0.53 | 4/5 | 1 | 3/3 | 0 | 6/6 | 0.80 | 1.00 |
| 0.54 | 4/5 | 1 | 3/3 | 0 | 6/6 | 0.80 | 1.00 |
| 0.55 | 4/5 | 1 | 3/3 | 0 | 6/6 | 0.80 | 1.00 |
| 0.56 | 4/5 | 1 | 3/3 | 0 | 6/6 | 0.80 | 1.00 |
| 0.57 | 4/5 | 1 | 3/3 | 0 | 6/6 | 0.80 | 1.00 |
| 0.58 | 4/5 | 1 | 3/3 | 0 | 6/6 | 0.80 | 1.00 |
| 0.59 | 4/5 | 1 | 3/3 | 0 | 6/6 | 0.80 | 1.00 |
| 0.60 | 4/5 | 1 | 3/3 | 0 | 6/6 | 0.80 | 1.00 |
| 0.61 | 4/5 | 1 | 3/3 | 0 | 6/6 | 0.80 | 1.00 |
| 0.62 | 4/5 | 1 | 3/3 | 0 | 6/6 | 0.80 | 1.00 |
| 0.63 | 4/5 | 1 | 3/3 | 0 | 6/6 | 0.80 | 1.00 |
| 0.64 | 4/5 | 1 | 3/3 | 0 | 6/6 | 0.80 | 1.00 |
| 0.65 | 4/5 | 1 | 3/3 | 0 | 6/6 | 0.80 | 1.00 |
| 0.66 | 4/5 | 1 | 3/3 | 0 | 6/6 | 0.80 | 1.00 |
| 0.67 | 4/5 | 1 | 3/3 | 0 | 5/6 | 0.80 | 1.00 |
| 0.68 | 4/5 | 1 | 3/3 | 0 | 4/6 | 0.80 | 1.00 |
| 0.69 | 4/5 | 1 | 3/3 | 0 | 3/6 | 0.80 | 1.00 |
| 0.70 | 4/5 | 1 | 3/3 | 0 | 3/6 | 0.80 | 1.00 |
| 0.71 | 4/5 | 1 | 3/3 | 0 | 3/6 | 0.80 | 1.00 |
| 0.72 | 4/5 | 1 | 3/3 | 0 | 2/6 | 0.80 | 1.00 |
| 0.73 | 4/5 | 1 | 3/3 | 0 | 1/6 | 0.80 | 1.00 |
| 0.74 | 4/5 | 1 | 3/3 | 0 | 0/6 | 0.80 | 1.00 |
| 0.75 | 4/5 | 1 | 3/3 | 0 | 0/6 | 0.80 | 1.00 |
| 0.76 | 4/5 | 1 | 3/3 | 0 | 0/6 | 0.80 | 1.00 |
| 0.77 | 4/5 | 1 | 3/3 | 0 | 0/6 | 0.80 | 1.00 |
| 0.78 | 3/5 | 1 | 3/3 | 0 | 0/6 | 0.60 | 1.00 |
| 0.79 | 3/5 | 1 | 3/3 | 0 | 0/6 | 0.60 | 1.00 |
| 0.80 | 3/5 | 1 | 3/3 | 0 | 0/6 | 0.60 | 1.00 |
| 0.81 | 3/5 | 1 | 3/3 | 0 | 0/6 | 0.60 | 1.00 |
| 0.82 | 3/5 | 1 | 3/3 | 0 | 0/6 | 0.60 | 1.00 |
| 0.83 | 3/5 | 1 | 3/3 | 0 | 0/6 | 0.60 | 1.00 |
| 0.84 | 3/5 | 1 | 3/3 | 0 | 0/6 | 0.60 | 1.00 |
| 0.85 | 3/5 | 1 | 3/3 | 0 | 0/6 | 0.60 | 1.00 |
| 0.86 | 3/5 | 1 | 3/3 | 0 | 0/6 | 0.60 | 1.00 |
| 0.87 | 1/5 | 1 | 3/3 | 0 | 0/6 | 0.20 | 1.00 |
| 0.88 | 1/5 | 0 | 3/3 | 0 | 0/6 | 0.20 | 1.00 |
| 0.89 | 1/5 | 0 | 3/3 | 0 | 0/6 | 0.20 | 1.00 |
| 0.90 | 1/5 | 0 | 3/3 | 0 | 0/6 | 0.20 | 1.00 |
| 0.91 | 1/5 | 0 | 3/3 | 0 | 0/6 | 0.20 | 1.00 |
| 0.92 | 0/5 | 0 | 3/3 | 0 | 0/6 | 0.00 | 1.00 |
| 0.93 | 0/5 | 0 | 3/3 | 0 | 0/6 | 0.00 | 1.00 |
| 0.94 | 0/5 | 0 | 3/3 | 0 | 0/6 | 0.00 | 1.00 |
| 0.95 | 0/5 | 0 | 3/3 | 0 | 0/6 | 0.00 | 1.00 |

Trade-off curve (every 0.05; `#` factual answered with evidence, `o` probe wrongly admitted, `x` sample false answer, `!` unsupported):

```
 0.00 |####oooooo!|
 0.05 |####oooooo!|
 0.10 |####oooooo!|
 0.15 |####oooooo!|
 0.20 |####oooooo!|
 0.25 |####oooooo!|
 0.30 |####oooooo!|
 0.35 |####oooooo!|
 0.40 |####oooooo!|
 0.45 |####oooooo!|
 0.50 |####oooooo!|
 0.55 |####oooooo!|
 0.60 |####oooooo!|
 0.65 |####oooooo!|
 0.70 |####ooo!   |
 0.75 |####!      |
 0.80 |###!       |
 0.85 |###!       |
 0.90 |#          |
 0.95 |           |
```

*M-1 proxy is the share of factual queries the gate would admit *and* whose key facts are in the retrieved context. It is **not** M-1, which is a judged 0-2 rubric score reported by `runner.py`.

The `sample false answers` column is 0 at every threshold by construction: all three sample refusals are decided by intent routing before retrieval. The `probe false answers` column is the threshold's real false-answer rate.


## What this run could and could not measure

M-3, M-4 and M-5 are measured in full without a chat model, because every refusal is a fixed policy decision that never calls one. M-1, M-2, M-6 and M-7 need a generated factual answer to inspect; with `LLM_PROVIDER=none` there is none, and the harness reports that instead of inventing a value.

The screens in `checks.py` are re-derived independently of `generation/validate.py` on purpose - an eval that called the product's own screens could never fail. Their agreement with the output screen is pinned by `tests/unit/test_eval_checks.py::test_eval_screens_agree_with_the_output_screen`, which includes the three false positives Phase 4 actually shipped.
