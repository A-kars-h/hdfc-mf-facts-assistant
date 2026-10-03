# Phase 0 - Corpus Viability Spike Report

- **Generated:** 2026-09-27T08:20:22+00:00
- **AMC:** HDFC Asset Management
- **Plan variant:** Direct Growth
- **Min extract chars (hard gate):** 1500
- **Result:** 5/5 pages PASS

A page below the character threshold is a probable client-rendered shell. Per FR-2 this is a HARD FAIL, not a warning: with only 5 pages, losing one means the assistant silently lacks an entire scheme.

## Per-page results

| page_id | Scheme | Category | HTTP | HTML bytes | Extracted chars | Method | Verdict |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `hdfc-large-cap` | HDFC Large Cap Fund - Direct Growth | Large Cap | 200 | 453,890 | 7,586 | plain | **PASS** |
| `hdfc-equity` | HDFC Equity Fund - Direct Growth | Flexi Cap | 200 | 494,209 | 9,552 | plain | **PASS** |
| `hdfc-elss` | HDFC ELSS Tax Saver Fund - Direct Plan - Growth | ELSS | 200 | 452,551 | 7,924 | plain | **PASS** |
| `hdfc-small-cap` | HDFC Small Cap Fund - Direct Growth | Small Cap | 200 | 496,884 | 9,526 | plain | **PASS** |
| `hdfc-balanced` | HDFC Balanced Advantage Fund - Direct Growth | Balanced Advantage | 200 | 815,645 | 33,158 | plain | **PASS** |

## Question-type coverage

The 7 question types named in `problemstatement.txt` line 34. Presence of the label, not verification of the value - eyeball the snippets below before relying on them.

| page_id | Expense ratio | Exit load | Minimum SIP | ELSS lock-in | Riskometer / risk level | Benchmark | Capital-gains statement download |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `hdfc-large-cap` | yes | yes | yes | **no** | yes | yes | **no** |
| `hdfc-equity` | yes | yes | yes | **no** | yes | yes | **no** |
| `hdfc-elss` | yes | yes | yes | yes | yes | yes | **no** |
| `hdfc-small-cap` | yes | yes | yes | **no** | yes | yes | **no** |
| `hdfc-balanced` | yes | yes | yes | **no** | yes | yes | **no** |

## Coverage across the whole corpus

| Question type | Covered | Note |
| --- | --- | --- |
| Expense ratio | 5/5 |  |
| Exit load | 5/5 |  |
| Minimum SIP | 5/5 |  |
| ELSS lock-in | 1/5 | Expected only on the ELSS page. |
| Riskometer / risk level | 5/5 | Verify per page - these vary by scheme. |
| Benchmark | 5/5 | Verify per page - these vary by scheme. |
| Capital-gains statement download | 0/5 | Expected absent - a Groww **account** help topic, not a scheme fact. Tracked as **OD-4**: extend the corpus under source line 27, or drop the question type. |

## Corpus composition - return/NAV density

**Why this matters:** the source forbids performance claims (line 41), but these pages carry substantial return data - period returns, a return calculator, NAV values. A 17% mean density means roughly one in six sentences is a figure we must not emit, so retrieval will routinely surface them as strong matches and the model will be tempted to quote them. FR-20's output screen is load-bearing, and Phase 2 should consider tagging return-heavy chunks so they can be deprioritised at retrieval time.

| page_id | Sentences | Return/NAV sentences | Density |
| --- | --- | --- | --- |
| `hdfc-large-cap` | 26 | 6 | **23%** |
| `hdfc-equity` | 37 | 6 | **16%** |
| `hdfc-elss` | 30 | 5 | **17%** |
| `hdfc-small-cap` | 27 | 5 | **19%** |
| `hdfc-balanced` | 62 | 5 | **8%** |

**Mean across corpus: 17%** return/NAV sentences.


## Structural delimiters available for chunking

The source requires the chunking strategy to be decided *from the data* (line 53). These counts say what the data can actually be split on. A low `period` count means a sentence-recursive splitter will emit enormous pseudo-sentences and blow the 200-token budget.

| page_id | Chars | `.` | `:` | newline | `%` | `₹` |
| --- | --- | --- | --- | --- | --- | --- |
| `hdfc-large-cap` | 7,586 | 119 | 3 | 1 | 80 | 20 |
| `hdfc-equity` | 9,552 | 169 | 3 | 1 | 117 | 20 |
| `hdfc-elss` | 7,924 | 124 | 3 | 1 | 83 | 20 |
| `hdfc-small-cap` | 9,526 | 158 | 3 | 1 | 117 | 20 |
| `hdfc-balanced` | 33,158 | 583 | 8 | 1 | 363 | 20 |

**Implications for Phase 2 — read before writing the chunker:**

1. **`newline` is 1 per page.** The spike flattens the DOM to a single line, destroying the block structure the HTML actually has (295 `<td>`, 75 `<tr>`, 12 `<h3>`, 6 `<p>` on the ELSS page). Chunk from a **structure-preserving re-parse of `data/raw/*.html`**, not from the flattened `.txt`. Table rows and headings are the natural chunk units.
2. **`.` occurs every ~60 characters**, so a sentence-level recursive splitter is viable and will land inside the 200-token budget. It is a reasonable *final* fallback, not the primary strategy.
3. **The text is a label-value stream**, not prose: `Expense ratio 1.21%`, `Min. for SIP ₹500`, `Exit load Nil`. Prefer splitting on field labels, and make each chunk **repeat its own label** so a retrieved chunk is independently answerable and BM25 can match the label text.
4. **Exit-load detail lives inside a `div.rodal` modal** (`.exitLoadStampDutyTax_*`), not the visible flow. It is present in the HTML and extractable, but a visibility-based extractor would silently drop it - and exit load is a source-named question type.


## Evidence snippets

### `hdfc-large-cap` - HDFC Large Cap Fund - Direct Growth

- **Expense ratio**: `6 ₹1,189.08 Min. for SIP ₹100 Fund size (AUM) ₹39,933.37 Cr Expense ratio 1.03% Rating 4 Return calculator Monthly investment ₹5,000 1 year ₹60,000 ₹58,430 -2.62 % 3 years ₹`
- **Exit load**: `2.7% Rank ( Equity Large Cap ) 45 17 14 -- Understand terms Exit Load Exit load, stamp duty and tax Exit load Exit load of 1% if redeemed within 1 year Stamp duty on inv`
- **Minimum SIP**: `HDFC Large Cap Fund Direct Growth is rated Very High risk. Minimum SIP Investment is set to ₹100. Minimum Lumpsum Investment is ₹100. Exit load of 1% if redeemed within 1`
- **Riskometer / risk level**: `Equity Large Cap Very High Risk +8.71 % 3Y annualised +0.14 % 1D 1M 6M 1Y 3Y 5Y All NAV: 25 Sep '26 ₹1,189.08 Min. for SIP ₹100 Fun`
- **Benchmark**: `ome by investing predominantly in Large-Cap companies. Fund benchmark NIFTY 100 Total Return Index Scheme Information Document(SID) Fund house Rank (total assets) #2 in`

### `hdfc-equity` - HDFC Equity Fund - Direct Growth

- **Expense ratio**: `₹2,214.57 Min. for SIP ₹100 Fund size (AUM) ₹1,13,606.47 Cr Expense ratio 0.77% Rating 5 Return calculator Monthly investment ₹5,000 1 year ₹60,000 ₹60,008 + 0.01 % 3 years`
- **Exit load**: `+14.2% Rank ( Equity Flexi Cap ) 13 3 3 -- Understand terms Exit Load Exit load, stamp duty and tax Exit load Exit load of 1% if redeemed within 1 year Stamp duty on inv`
- **Minimum SIP**: `HDFC Flexi Cap Direct Plan Growth is rated Very High risk. Minimum SIP Investment is set to ₹100. Minimum Lumpsum Investment is ₹100. Exit load of 1% if redeemed within 1`
- **Riskometer / risk level**: `Equity Flexi Cap Very High Risk +15.42 % 3Y annualised +0.28 % 1D 1M 6M 1Y 3Y 5Y All NAV: 25 Sep '26 ₹2,214.57 Min. for SIP ₹100 Fu`
- **Benchmark**: `antly invested in equity & equity related instruments. Fund benchmark NIFTY 500 Total Return Index Scheme Information Document(SID) Fund house Rank (total assets) #2 in`

### `hdfc-elss` - HDFC ELSS Tax Saver Fund - Direct Plan - Growth

- **Expense ratio**: `6 ₹1,447.38 Min. for SIP ₹500 Fund size (AUM) ₹15,991.78 Cr Expense ratio 1.21% Rating 5 Return calculator Monthly investment ₹5,000 1 year ₹60,000 ₹57,940 -3.43 % 3 years ₹`
- **Exit load**: `.2% +17.1% Rank ( Equity ELSS ) 13 5 17 -- Understand terms Exit Load Exit load, stamp duty and tax Exit load Nil Stamp duty on investment: 0.005% (from July 1st, 2020)`
- **Minimum SIP**: `Tax Saver Fund Direct Plan Growth is rated Very High risk. Minimum SIP Investment is set to ₹500. Minimum Lumpsum Investment is ₹500. ; Investment Objective The scheme se`
- **ELSS lock-in**: `ELSS • 3Y Lock-in Equity ELSS Very High Risk +12.47 % 3Y annualised +0.38 % 1D 1M 6M 1Y 3Y 5Y All NAV: 25 Sep '26 ₹1,`
- **Riskometer / risk level**: `ELSS • 3Y Lock-in Equity ELSS Very High Risk +12.47 % 3Y annualised +0.38 % 1D 1M 6M 1Y 3Y 5Y All NAV: 25 Sep '26 ₹1,447.38 Min. for SIP ₹500 Fu`
- **Benchmark**: `predominantly of equity & equity related instruments. Fund benchmark NIFTY 500 Total Return Index Scheme Information Document(SID) Fund house Rank (total assets) #2 in`

### `hdfc-small-cap` - HDFC Small Cap Fund - Direct Growth

- **Expense ratio**: `'26 ₹159.82 Min. for SIP ₹100 Fund size (AUM) ₹41,890.86 Cr Expense ratio 0.78% Rating 3 Return calculator Monthly investment ₹5,000 1 year ₹60,000 ₹61,449 + 2.42 % 3 years`
- **Exit load**: `20.4% Rank ( Equity Small Cap ) 34 18 5 -- Understand terms Exit Load Exit load, stamp duty and tax Exit load Exit load of 1% if redeemed within 1 year Stamp duty on inv`
- **Minimum SIP**: `HDFC Small Cap Fund Direct Growth is rated Very High risk. Minimum SIP Investment is set to ₹100. Minimum Lumpsum Investment is ₹100. Exit load of 1% if redeemed within 1`
- **Riskometer / risk level**: `Equity Small Cap Very High Risk +11.08 % 3Y annualised -0.06 % 1D 1M 6M 1Y 3Y 5Y All NAV: 25 Sep '26 ₹159.82 Min. for SIP ₹100 Fund`
- **Benchmark**: `ome by investing predominantly in Small-Cap companies. Fund benchmark BSE 250 SmallCap Total Return Index Scheme Information Document(SID) Fund house Rank (total assets)`

### `hdfc-balanced` - HDFC Balanced Advantage Fund - Direct Growth

- **Expense ratio**: `6 ₹557.73 Min. for SIP ₹100 Fund size (AUM) ₹1,07,295.79 Cr Expense ratio 0.78% Rating 5 Return calculator Monthly investment ₹5,000 1 year ₹60,000 ₹59,315 -1.14 % 3 years ₹`
- **Exit load**: `ybrid Dynamic Asset Allocation ) 7 1 -- -- Understand terms Exit Load Exit load, stamp duty and tax Exit load Exit Load for units in excess of 15% of the investment,1% w`
- **Minimum SIP**: `anced Advantage Fund Direct Growth is rated Very High risk. Minimum SIP Investment is set to ₹100. Minimum Lumpsum Investment is ₹100. Exit Load for units in excess of 15%`
- **Riskometer / risk level**: `Hybrid Dynamic Asset Allocation Very High Risk +11.02 % 3Y annualised +0.21 % 1D 1M 6M 1Y 3Y 5Y All NAV: 25 Sep '26 ₹557.73 Min. for SIP ₹100 Fund`
- **Benchmark**: `ome from a dynamic mix of equity and debt investments. Fund benchmark NIFTY 50 Hybrid Composite Debt 50:50 Index Scheme Information Document(SID) Fund house Rank (total`

## Errors

None.
