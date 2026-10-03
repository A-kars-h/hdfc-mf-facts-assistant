"""Synthetic corpus fixtures that mimic the real Groww page structure.

Deliberately copies the traps found in Phase 0/2, because a fixture that is
easier than the real page tests nothing:

* the scheme name / riskometer / lock-in live inside a `<header>` element
  (dropping headers by tag silently deletes the riskometer),
* exit load lives in a `div.rodal` modal (a visibility filter drops it),
* fund facts are label/value `div.flex.flex-column` rows, not `<p>` or tables,
* the site nav is outside the content root, and there is no `<main>`.
"""

from __future__ import annotations

SCHEME = "HDFC Equity Fund Direct Growth"

# A plain string with a __SCHEME__ placeholder rather than an f-string: the
# fixture contains JSON braces in a <script> tag, which an f-string would try
# to interpret as a format spec.
PAGE_HTML = """<!doctype html>
<html><body>
<div class="root"><div class="__next">
  <!-- Site chrome OUTSIDE the content root. A parser with no content-root
       selector ingests all of this. -->
  <nav class="navbar headerNav">
    <a href="/etf-screener">ETF Screener</a>
    <a href="/ipo">IPO</a>
    <a href="/demat-account">Demat Account</a>
  </nav>

  <div class="pw14Container container">
    <div class="pw14MainWrapper layout-container">
      <div class="pw14ContentWrapper backgroundPrimary layout-main">
        <div class="layout-main width100 flex flex-column">

          <header class="">
            <section class="flex flex-column header_schemeNameContainer">
              <div class="valign-wrapper pills_container">
                <a><div class="pill12Pill"><span class="bodyBaseHeavy">Equity Flexi Cap</span></div></a>
                <a><div class="pill12Pill"><span class="bodySmallHeavy">Very High Risk</span></div></a>
              </div>
              <h1 class="headerTitle">__SCHEME__</h1>
            </section>
          </header>

          <div class="fundDetails_fundDetailsContainer">
            <div class="flex flex-column fundDetails_gap4">
              <div class="flex flex-column fundDetails_gap4">
                <div class="valign-wrapper bodyLarge contentTertiary">Expense ratio</div>
                <div class="bodyXLargeHeavy contentPrimary">0.77%</div>
              </div>
              <div class="flex flex-column fundDetails_gap4">
                <div class="valign-wrapper bodyLarge contentTertiary">Min. for SIP</div>
                <div class="bodyXLargeHeavy contentPrimary">&#8377;100</div>
              </div>
              <div class="flex flex-column fundDetails_gap4">
                <div class="valign-wrapper bodyLarge contentTertiary">Fund benchmark</div>
                <div class="bodyXLargeHeavy contentPrimary">NIFTY 500 Total Return Index</div>
              </div>
              <div class="flex flex-column fundDetails_gap4">
                <div class="valign-wrapper bodyLarge contentTertiary">Fund size (AUM)</div>
                <div class="bodyXLargeHeavy contentPrimary">&#8377;1,13,606.47 Cr</div>
              </div>
            </div>
          </div>

          <section class="returnsSection">
            <h2>Returns and rankings</h2>
            <table>
              <caption>Fund returns</caption>
              <tr><th>Period</th><th>Return</th></tr>
              <tr><td>1 year</td><td>+ 0.01 %</td></tr>
              <tr><td>3 years</td><td>+ 14.2%</td></tr>
            </table>
            <p>Average of the yearly returns of a mutual fund over a given period.</p>
          </section>

          <section class="exitLoadSection">
            <h2>Exit load</h2>
            <!-- The exit-load detail lives in a MODAL. -->
            <div class="rodal rodal-zoom-leave">
              <div class="rodal-dialog">
                <div class="exitLoadStampDutyTax_popupBody">
                  <h5 class="exitLoadStampDutyTax_termBlock">Exit load, stamp duty and tax</h5>
                  <p>Exit load of 1% if redeemed within 1 year.</p>
                  <p>Stamp duty on investment: 0.005% (from July 1st, 2020).</p>
                </div>
              </div>
            </div>
          </section>

          <footer class="footerTopSection">
            <a href="/disclaimer">Disclaimer</a>
            <a href="/terms">Terms</a>
          </footer>

        </div>
      </div>
    </div>
  </div>
</div></div>
<script>window.__DATA__ = {"noise": true};</script>
</body></html>
""".replace("__SCHEME__", SCHEME)

# Same shape, but the content is far too thin to be usable.
THIN_HTML = """<!doctype html>
<html><body>
<div class="pw14MainWrapper layout-container"><div class="pw14ContentWrapper">
  <div class="layout-main">
    <h1>HDFC Thin Fund Direct Growth</h1>
    <p>Very little here.</p>
  </div>
</div></div>
</body></html>
"""


def corpus_yaml(page_ids: list[str], min_extract_chars: int = 1500) -> str:
    """A minimal corpus.yaml body for the given page ids.

    `min_extract_chars` must match the value passed to Settings: load_corpus
    deliberately rejects the two drifting apart, so a fixture that sets one and
    not the other fails loudly rather than testing a page threshold that the
    real pipeline would never use.
    """
    lines = [
        "amc: HDFC Asset Management",
        "plan_variant: Direct Growth",
        f"min_extract_chars: {min_extract_chars}",
        "pages:",
    ]
    for pid in page_ids:
        lines += [
            f"  - page_id: {pid}",
            f"    scheme: {SCHEME}",
            "    category: Flexi Cap",
            f"    source_url: https://groww.in/mutual-funds/{pid}",
        ]
    return "\n".join(lines) + "\n"
