# Screenshots — what the UI shows

**These are text renders, not images.** This machine has no browser and no
screen-capture tooling, so a pixel screenshot of the running Streamlit app could
not be taken without fabricating one. Instead each file below is produced by
**driving the real `src/ragbot/ui/app.py`** through Streamlit's own `AppTest`
— the same harness `tests/unit/test_ui_app.py` uses — and transcribing exactly
what it rendered.

Every answer in them is replayed from a real eval run against the live index and
a live LLM (`artifacts/sample_qa.md`), so the text, the citation and the date are
the product's actual output rather than a mock-up.

| File | Shows |
|---|---|
| [`01_welcome_and_starters.md`](01_welcome_and_starters.md) | Welcome, three starters, persistent disclaimer |
| [`02_factual_answer_min_sip.md`](02_factual_answer_min_sip.md) | Factual answer: minimum SIP, one link, Last updated |
| [`03_opinion_refusal.md`](03_opinion_refusal.md) | Opinion refusal (Q6) - educational link missing, stated honestly |
| [`04_out_of_corpus_refusal.md`](04_out_of_corpus_refusal.md) | Out-of-corpus refusal (Q8) - HDFC Mid Cap |
| [`05_chunk_inspector.md`](05_chunk_inspector.md) | Chunk inspector, expanded |

---

## Still missing

- **Pixel screenshots** of the running app — needs a browser.
- The **≤3-minute demo recording** is **not** missing: it is
  [on Google Drive](https://drive.google.com/file/d/1wG_o83w-RLmd-N0AX-HHjm1Bt15drxhJ/view?usp=sharing),
  2m 42.6s verified from the file's `mvhd` atom.

No placeholder image has been committed in place of the pixel screenshots.
