# D-4 Sample Q&A (8 queries)

Generated from a real eval run against the live index and a live LLM (`src.ragbot.eval.runner.run_set`). Not hand-written. Regenerate with:

```
python scripts/phase8_eval_capture.py   # run the 8 queries, capture the results
python scripts/phase8_sample_qa.py      # render this file from that capture
```

- Corpus: 5 HDFC Direct Growth pages
- LLM provider in this run: `openai` / `qwen/qwen3.8-27b`
- `SIMILARITY_THRESHOLD` in force: **0.7562** - read from `artifacts/calibration.json`, derived by `python -m src.ragbot.eval.calibrate`, never typed in
- Judged M-1 is in `artifacts/eval_report.md` (this capture ran with the judge off; see the metrics table below)
- Generated: 2026-10-02 15:56 UTC

---

## Q1 - factual

**Q:** What is the expense ratio of HDFC Large Cap Fund Direct Growth?

**Outcome:** ANSWERED  |  intent `factual`  |  raw_dense_max 0.92

> The expense ratio for HDFC Large Cap Fund - Direct Growth is 1.03% .

- Source: [https://groww.in/mutual-funds/hdfc-large-cap-fund-direct-growth](https://groww.in/mutual-funds/hdfc-large-cap-fund-direct-growth)
- Last updated from sources: 2026-09-27
- Expected source (from `eval/sample_set.jsonl`): https://groww.in/mutual-funds/hdfc-large-cap-fund-direct-growth
- Expected facts: Expense ratio; 1.03%
- Deterministic checks: ALL PASS

## Q2 - factual

**Q:** What is the exit load on HDFC Small Cap Fund Direct Growth?

**Outcome:** ANSWERED  |  intent `factual`  |  raw_dense_max 0.8633

> The HDFC Small Cap Fund - Direct Growth has an exit load of 1% if redeemed within 1 year . This exit load structure has been in place since 01 Jan 2013 .

- Source: [https://groww.in/mutual-funds/hdfc-small-cap-fund-direct-growth](https://groww.in/mutual-funds/hdfc-small-cap-fund-direct-growth)
- Last updated from sources: 2026-09-27
- Expected source (from `eval/sample_set.jsonl`): https://groww.in/mutual-funds/hdfc-small-cap-fund-direct-growth
- Expected facts: Exit load; within 1 year
- Deterministic checks: ALL PASS

## Q3 - factual

**Q:** What is the minimum SIP amount for HDFC ELSS Tax Saver Fund Direct Plan Growth?

**Outcome:** ANSWERED  |  intent `factual`  |  raw_dense_max 0.8678

> The minimum SIP amount for the HDFC ELSS Tax Saver Fund - Direct Plan - Growth is ₹500 .

- Source: [https://groww.in/mutual-funds/hdfc-elss-tax-saver-fund-direct-plan-growth](https://groww.in/mutual-funds/hdfc-elss-tax-saver-fund-direct-plan-growth)
- Last updated from sources: 2026-09-27
- Expected source (from `eval/sample_set.jsonl`): https://groww.in/mutual-funds/hdfc-elss-tax-saver-fund-direct-plan-growth
- Expected facts: Min. for SIP; 500
- Deterministic checks: ALL PASS

## Q4 - factual

**Q:** What is the lock-in period for HDFC ELSS Tax Saver Fund?

**Outcome:** ANSWERED  |  intent `factual`  |  raw_dense_max 0.7764

> The lock-in period for the HDFC ELSS Tax Saver Fund is 3 years .

- Source: [https://groww.in/mutual-funds/hdfc-elss-tax-saver-fund-direct-plan-growth](https://groww.in/mutual-funds/hdfc-elss-tax-saver-fund-direct-plan-growth)
- Last updated from sources: 2026-09-27
- Expected source (from `eval/sample_set.jsonl`): https://groww.in/mutual-funds/hdfc-elss-tax-saver-fund-direct-plan-growth
- Expected facts: 3Y; Lock-in
- Deterministic checks: ALL PASS

## Q5 - factual

**Q:** What is the benchmark of HDFC Balanced Advantage Fund Direct Growth?

**Outcome:** ANSWERED  |  intent `factual`  |  raw_dense_max 0.8706

> The provided corpus does not contain the benchmark for HDFC Balanced Advantage Fund - Direct Growth.

- Source: [https://groww.in/mutual-funds/hdfc-balanced-advantage-fund-direct-growth](https://groww.in/mutual-funds/hdfc-balanced-advantage-fund-direct-growth)
- Last updated from sources: 2026-09-27
- Expected source (from `eval/sample_set.jsonl`): https://groww.in/mutual-funds/hdfc-balanced-advantage-fund-direct-growth
- Expected facts: Fund benchmark; NIFTY 50 Hybrid Composite Debt 50:50
- Deterministic checks: ALL PASS

## Q6 - opinion

**Q:** Should I buy HDFC Large Cap for a 5-year goal?

**Outcome:** REFUSED  |  intent `opinion`  |  raw_dense_max n/a - routed before retrieval

> I answer with verified facts about these funds rather than with a view on whether an investment in any of them suits you. No verified investor-education page is available in this deployment yet, so there is no link I can point you to without risking a wrong one.

- Source: none - refusal paths cite nothing by design
- Educational link: **none available** - `education_links.yml` ships empty, so the refusal says so rather than inventing a URL (OD-2)
- Deterministic checks: ALL PASS

## Q7 - opinion

**Q:** Which of these five is the best performing fund?

**Outcome:** REFUSED  |  intent `opinion`  |  raw_dense_max n/a - routed before retrieval

> I answer with verified facts about these funds rather than with a view on whether an investment in any of them suits you. No verified investor-education page is available in this deployment yet, so there is no link I can point you to without risking a wrong one.

- Source: none - refusal paths cite nothing by design
- Educational link: **none available** - `education_links.yml` ships empty, so the refusal says so rather than inventing a URL (OD-2)
- Deterministic checks: ALL PASS

## Q8 - out of scope

**Q:** What is the expense ratio of the HDFC Mid Cap Fund?

**Outcome:** REFUSED  |  intent `out_of_scope`  |  raw_dense_max n/a - routed before retrieval

> That is outside what I can answer. I cover verified facts from a fixed set of HDFC mutual fund pages - scheme details, fees and expense ratios, minimum investment amounts, exit loads, tax treatment, benchmark, riskometer level, holdings, and fund manager and company information. I do not give investment advice, and I do not answer from outside that material.

- Source: none - refusal paths cite nothing by design
- Deterministic checks: ALL PASS

---

## Metrics from the same run

| Metric | Value | Target | Status |
|---|---|---|---|
| M-1 | n/a | >= 1.6 / 2 | unavailable |
| M-2 | 10/10 | 5/5 | measured |
| M-3 | 3/3 | 3/3 | measured |
| M-4 | 0/8 | 0 | measured |
| M-5 | 0/8 | 0 | measured |
| M-6 | 5/5 | 8/8 | measured |
| M-7 | 10/10 | 5/5 | measured |

`M-1` reads `unavailable` here because this capture ran with the judge disabled. The judged run - model, version, rubric and prompt fingerprint - is in `artifacts/eval_report.md`.

## One honest observation

**A confident non-answer passes every automated check.** Q5 (benchmark of HDFC Balanced Advantage Fund) is **answered**, not refused, with the text "The provided corpus does not contain the benchmark for HDFC Balanced Advantage Fund - Direct Growth." - while the benchmark **is** in the corpus (verified in Phase 0), the gate opened at `raw_dense_max` 0.8706, and a citation to the correct page was attached.

Every deterministic rule was satisfied: one in-corpus link, one sentence, no advice, no return figure, correct `last_updated`. `run_checks` reported no failures. Nothing in the harness can distinguish this from a good answer; only the M-1 judge can. Recorded rather than hidden - see `artifacts/prd_checklist.md`.
