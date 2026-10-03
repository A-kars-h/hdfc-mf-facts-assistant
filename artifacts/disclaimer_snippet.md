# D-5 — Disclaimer snippet

The exact string rendered in the UI, as a persistent note on every screen and
next to every answer.

## The string

```
Facts-only. No investment advice.
```

## Where it comes from

It is the `DISCLAIMER` constant in `src/ragbot/ui/app.py`:

```python
DISCLAIMER = "Facts-only. No investment advice."
```

Rendered with `st.info(DISCLAIMER, icon="⚠️")`, which re-renders on **every**
Streamlit rerun — so it is persistent, not a banner that appears once and scrolls
away. It sits below the three starter questions and above the input and every
rendered answer, because the whole product claim is that no advice is given and
the reader must be able to see that at a glance.

## Use it verbatim

Copy the string above. Do not paraphrase it, do not soften it, and do not drop
"advice" — the refusal is the behaviour, this line is the disclosure that the
behaviour exists.