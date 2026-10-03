# Demo Script — ≤3 minutes

Timed beat sheet for D-1. Follow it verbatim; the point is to show the
**refusals** as clearly as the answers, because that is what the product claims.

> **Recorded:** [HDFC MF facts assistant - Demo video.mp4](https://drive.google.com/file/d/1wG_o83w-RLmd-N0AX-HHjm1Bt15drxhJ/view?usp=sharing)
> — Google Drive, shared "anyone with the link". Duration **verified from the
> file's own `mvhd` atom: 162.58 s = 2m 42.6s**, within the ≤3-minute limit.
> Reproduce with `python scripts/verify_demo_duration.py 1wG_o83w-RLmd-N0AX-HHjm1Bt15drxhJ`.
> The run was **rehearsed twice before recording** (author-attested, confirmed
> 2026-10-03). The beat sheet below is the script the recording follows.

## Before you start

```powershell
python scripts/phase8_eval_capture.py   # optional: confirms the corpus and threshold
python -m streamlit run src/ragbot/ui/app.py
```

Open `http://127.0.0.1:8501`. Leave `data/chroma` populated — re-ingesting is
skipped by hash and costs nothing, but a cold index costs a model load.

The three starter buttons are the golden-set queries (Q3, Q6, Q8) from
`eval/sample_set.jsonl`, so the demo, the eval report and `sample_qa.md` cannot
disagree with each other.

---

## Beat sheet

| Time | Beat | What to show | What to say |
|---|---|---|---|
| **0:00** | Corpus and provenance | Open `artifacts/manifest.json`. Point at `pages[].fetched_at` — five different per-page fetch dates, not one global timestamp. Then open `artifacts/source_list.csv`. | "Five HDFC Direct Growth pages, fetched once. Every answer's *Last updated from sources* comes from the individual page's own fetch date, so it's truthful." |
| **0:25** | Minimum SIP — a real answer | Click starter 1 (ELSS minimum SIP). Show the answer, the single source link, and the **Last updated from sources:** line. | "One sentence, one citation, and the date that page was fetched. The answer is *₹500* — straight off the page, nothing from memory." |
| **0:50** | Chunk inspector | Expand **Show retrieved chunks (5 sent to the model)**. Point at `raw dense`, `fused rank`, the chunk ids and the fact rows. | "Here's exactly what the model was given. `raw dense` is what the confidence gate reads; `fused rank` is ordering only — they're separate fields on purpose, so a rank score can never be thresholded by accident." |
| **1:15** | Opinion refusal | Click starter 2 (*Should I buy HDFC Large Cap?*). | "It refuses. Not because retrieval was weak — it never even searched. And note it says plainly that no verified education link is available, rather than inventing a plausible-looking URL." |
| **1:50** | Performance refusal | Type *Which of these five is the best performing fund?* | "Refused. Comparing funds is exactly the thing that turns a facts bot into an adviser." |
| **2:10** | Out-of-corpus refusal | Click starter 3 (*expense ratio of the HDFC Mid Cap Fund?*). | "HDFC Mid Cap is a real HDFC scheme — it's just not in our corpus. We decline and say what we do cover, rather than answering from the model's memory of a fund we never read." |
| **2:30** | Limits, honestly | One line, no slides. | "Five pages, one AMC, English only, and a point-in-time snapshot. The threshold is calibrated, not guessed — and where it's wrong, it refuses." |
| **2:50** | Close | — | "Facts-only. No investment advice." |

---

## Do not do these

- **Do not skip the two refusals to save time.** They are the deliverable.
- **Do not demo a question the corpus cannot answer** and then talk over the refusal.
- **Do not claim the educational link works.** It does not exist (OD-2) — the UI
  says so, and that honesty is the point.
- **Do not show the similarity threshold value on screen.** A refusal never
  reveals it, and a demo that teaches the bar teaches people to aim at it.

## If asked "why does it refuse so much?"

The gate reads raw cosine similarity against a threshold derived from a sweep
(`artifacts/calibration.json`, 0.7562). That is a real trade-off, not a tuning
bug: measured across question shapes, `raw_dense_max` ranges from 0.82 for a
scheme-specific benchmark question down to 0.27 for a bare *lock-in period*
question whose retrieved chunk was nonetheless correct. One global scalar cannot
serve both, so some correct questions are refused. It is recorded as OQ-4 in
`docs/implementation.md`, and the fix is a per-intent threshold — not a number
picked to make this demo look good.