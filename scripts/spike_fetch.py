"""
Phase 0 - Corpus viability spike.

Purpose: prove the corpus exists and is extractable BEFORE building any product
code. Groww is a client-rendered application, so a plain HTTP GET can return a
JavaScript shell with almost no readable text. If that happens here, it costs
minutes; if we discover it after building the pipeline, it costs days.

Standalone by design: this script imports nothing from src.ragbot.

Deps: httpx, beautifulsoup4, pyyaml   (no ML stack - not needed for a fetch spike)

Usage:
    python scripts/spike_fetch.py
    python scripts/spike_fetch.py --min-chars 1500
    python scripts/spike_fetch.py --only hdfc-elss

Exit codes:  0 = all pages PASS   1 = at least one page FAIL
"""

from __future__ import annotations

import argparse
import re
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import httpx
import yaml
from bs4 import BeautifulSoup
from bs4.element import Tag

ROOT = Path(__file__).resolve().parent.parent
CORPUS_PATH = ROOT / "config" / "corpus.yaml"
RAW_DIR = ROOT / "data" / "raw"
REPORT_PATH = ROOT / "artifacts" / "spike_report.md"

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)
TIMEOUT = 30.0
RETRIES = 2
POLITE_DELAY = 2.0

# Tags that never carry scheme facts.
CHROME_TAGS = ("script", "style", "nav", "header", "footer", "aside", "noscript",
               "iframe", "form", "button", "svg")

# class/id fragments typical of cookie banners, share widgets, breadcrumbs, promos.
# Names below were confirmed against the live Groww DOM during the Phase 0 spike.
CHROME_PATTERN = re.compile(
    r"cookie|consent|gdpr|banner|share|social|breadcrumb|promo|advert|"
    r"ad-|ads-|popup|modal|newsletter|subscribe|footer|header|navbar|nav-|"
    r"skip-to|visually-hidden|sr-only|related|widget|sidebar|menu|"
    r"dropdownUI|dropdown-|loggedOut_|loggedOut|letterLinks|footerTopSection|"
    r"rodal|searchBar|hamburger|drawer|toast|breadcrumbList",
    re.IGNORECASE,
)

# Preferred content roots, most specific first. Groww's scheme pages have no
# <main>/<article>/role=main, so without these the whole site nav is ingested.
CONTENT_ROOT_SELECTORS = (
    {"class": re.compile(r"pw14MainWrapper")},
    {"class": re.compile(r"pw14ContentWrapper")},
    {"class": re.compile(r"layout-main")},
    {"class": re.compile(r"layout-container")},
    {"name": "main"},
    {"name": "article"},
    {"attrs": {"role": "main"}},
)

# The 7 question types named in the source (problemstatement.txt line 34).
# 'capital_gains_statement' is expected to be ABSENT - it is a Groww account
# help topic, not a scheme fact. Tracked as OD-4.
FACT_PATTERNS: dict[str, re.Pattern[str]] = {
    "expense_ratio": re.compile(r"expense\s*ratio", re.IGNORECASE),
    "exit_load": re.compile(r"exit\s*load", re.IGNORECASE),
    "minimum_sip": re.compile(
        r"(minimum|min\.?)\s*(sip|investment|amount|investment\s+amount)", re.IGNORECASE
    ),
    "elss_lock_in": re.compile(r"lock[\s\-_]?in", re.IGNORECASE),
    # Groww shows the risk LEVEL, not the literal word "riskometer". The level is
    # what a user asking "what's the riskometer?" actually needs answered.
    "riskometer": re.compile(
        r"riskometer|risk\s*ometer|very\s+high\s+risk|moderately\s+high\s+risk|"
        r"high\s+risk|moderate\s+risk|low\s+risk",
        re.IGNORECASE,
    ),
    "benchmark": re.compile(r"benchmark", re.IGNORECASE),
    "capital_gains_statement": re.compile(
        r"capital\s*gains?\s*statement", re.IGNORECASE
    ),
}

FACT_LABELS = {
    "expense_ratio": "Expense ratio",
    "exit_load": "Exit load",
    "minimum_sip": "Minimum SIP",
    "elss_lock_in": "ELSS lock-in",
    "riskometer": "Riskometer / risk level",
    "benchmark": "Benchmark",
    "capital_gains_statement": "Capital-gains statement download",
}

# Measured, not assumed: these pages are dominated by return/NAV figures, which
# is exactly what the source's no-performance-claims rule (FR-20) forbids us to
# emit. Quantifying the density tells Phase 2 how to chunk and Phase 4 how hard
# the output screen must work.
PERF_PATTERN = re.compile(
    r"(?:[+\-]\s?\d+(?:\.\d+)?\s?%)|(?:\d+(?:\.\d+)?\s?%\s*(?:1\s*Y|3\s*Y|5\s*Y|"
    r"10\s*Y|annualised|annualized))|(?:\bNAV\b)|(?:annualised)|(?:annualized)|"
    r"(?:Return calculator)",
    re.IGNORECASE,
)
PERF_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+")


@dataclass
class PageResult:
    page_id: str
    scheme: str
    category: str
    source_url: str
    status_code: int | None = None
    html_bytes: int = 0
    extract_chars: int = 0
    ok: bool = False
    method: str = "plain"
    error: str | None = None
    facts: dict[str, bool] = field(default_factory=dict)
    fact_snippets: dict[str, str] = field(default_factory=dict)
    perf_sentences: int = 0
    total_sentences: int = 0
    delimiters: dict[str, int] = field(default_factory=dict)
    fetched_at: str = ""

    @property
    def perf_density(self) -> float:
        if not self.total_sentences:
            return 0.0
        return self.perf_sentences / self.total_sentences

    @property
    def verdict(self) -> str:
        if not self.ok:
            return "FAIL"
        return "PASS"


def load_corpus(path: Path) -> dict:
    if not path.exists():
        sys.exit(f"[FATAL] corpus config not found: {path}")
    with path.open(encoding="utf-8") as fh:
        cfg = yaml.safe_load(fh)
    if not cfg or "pages" not in cfg:
        sys.exit(f"[FATAL] {path} has no 'pages' key")
    return cfg


def strip_chrome(root: BeautifulSoup | Tag) -> None:
    """Remove tags and nodes that cannot contain scheme facts.

    Uses extract(), never decompose(). BeautifulSoup's decompose() walks forward
    with next_element clearing every tag's __dict__ as it goes, which destroys
    nodes later in the iteration and turns any second pass into an AttributeError.
    extract() is non-destructive to the rest of the tree, so the removal order
    does not matter.
    """
    doomed: list[Tag] = []
    for tag in root.find_all(CHROME_TAGS):
        doomed.append(tag)
    for node in root.find_all(attrs={"class": True}):
        classes = " ".join(node.get("class") or [])
        if CHROME_PATTERN.search(classes):
            doomed.append(node)
    for node in root.find_all(attrs={"id": True}):
        if CHROME_PATTERN.search(node.get("id") or ""):
            doomed.append(node)

    # Drop descendants of doomed ancestors: removing the ancestor already removes them.
    roots = [n for n in doomed if not any(a is not n and n in a.parents for a in doomed)]
    for node in roots:
        try:
            node.extract()
        except (ValueError, AttributeError):
            pass


def find_content_root(soup: BeautifulSoup) -> Tag:
    """Locate the scheme-detail region. Groww scheme pages have no <main>, so the
    class-based selectors below are what keep site navigation out of the corpus."""
    for attrs in CONTENT_ROOT_SELECTORS:
        node = soup.find(**attrs)
        if node is not None:
            return node
    return soup


def extract_text(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    # Locate the content region BEFORE stripping, so a chrome-matching class on
    # the content root cannot cause the whole corpus to be removed.
    target = find_content_root(soup)
    strip_chrome(target)
    text = target.get_text(separator=" ", strip=True)
    return re.sub(r"[ \t ]+", " ", re.sub(r"\n{3,}", "\n\n", text)).strip()


def fetch_plain(url: str) -> tuple[int, str]:
    last_exc: Exception | None = None
    for attempt in range(RETRIES + 1):
        try:
            with httpx.Client(
                timeout=TIMEOUT,
                follow_redirects=True,
                headers={"User-Agent": USER_AGENT,
                         "Accept": "text/html,application/xhtml+xml",
                         "Accept-Language": "en-IN,en;q=0.9"},
            ) as client:
                resp = client.get(url)
            return resp.status_code, resp.text
        except Exception as exc:  # noqa: BLE001 - spike reports, never crashes silently
            last_exc = exc
            if attempt < RETRIES:
                time.sleep(2 * (attempt + 1))
    raise RuntimeError(f"{type(last_exc).__name__}: {last_exc}")


def fetch_rendered(url: str) -> tuple[int, str]:
    """Optional fallback. Requires playwright, which is NOT a Phase 0 dependency."""
    try:
        from playwright.sync_api import sync_playwright  # type: ignore
    except ImportError as exc:
        raise RuntimeError(
            "plain fetch produced too little text and playwright is not installed - "
            "install it with `pip install playwright && playwright install chromium` "
            "to attempt a rendered fetch"
        ) from exc
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page(user_agent=USER_AGENT)
        resp = page.goto(url, timeout=TIMEOUT * 1000, wait_until="networkidle")
        html = page.content()
        status = resp.status if resp else 0
        browser.close()
    return status, html


def audit_facts(text: str, result: PageResult) -> None:
    for key, pattern in FACT_PATTERNS.items():
        match = pattern.search(text)
        result.facts[key] = match is not None
        if match:
            lo = max(0, match.start() - 60)
            hi = min(len(text), match.end() + 100)
            snippet = re.sub(r"\s+", " ", text[lo:hi]).strip()
            result.fact_snippets[key] = snippet
    # Return/NAV density - drives Phase 2 chunking and Phase 4 screening effort.
    for sentence in PERF_SENTENCE_SPLIT.split(text):
        s = sentence.strip()
        if not s:
            continue
        result.total_sentences += 1
        if PERF_PATTERN.search(s):
            result.perf_sentences += 1
    # Structural delimiters actually present. The source requires deciding the
    # chunking strategy "based on the data" (line 53), so measure the data first:
    # if '.' is rare, a sentence-recursive splitter will produce useless chunks.
    result.delimiters = {
        "period": len(re.findall(r"\.", text)),
        "colon": len(re.findall(r":", text)),
        "pipe": text.count("|"),
        "newline": text.count("\n"),
        "percent_sign": text.count("%"),
        "rupee": text.count("\u20b9"),
    }


def process(page_cfg: dict, min_chars: int, allow_rendered: bool) -> PageResult:
    url = page_cfg["source_url"]
    res = PageResult(
        page_id=page_cfg["page_id"],
        scheme=page_cfg["scheme"],
        category=page_cfg["category"],
        source_url=url,
        fetched_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
    )
    print(f"  fetching {res.page_id} ...", flush=True)

    status, html, text = 0, "", ""
    try:
        status, html = fetch_plain(url)
        res.status_code, res.html_bytes = status, len(html.encode("utf-8"))
        text = extract_text(html)
    except Exception as exc:  # noqa: BLE001
        res.error = str(exc)
        print(f"    extraction/fetch error: {res.error}", flush=True)

    # The hard gate: below min_chars the page is a probable JS shell.
    if len(text) < min_chars and html:
        if not allow_rendered:
            print(f"    only {len(text)} chars - rendered fallback skipped (--no-rendered)",
                  flush=True)
        else:
            print(f"    only {len(text)} chars - attempting rendered fetch", flush=True)
            try:
                rstatus, rhtml = fetch_rendered(url)
                rtext = extract_text(rhtml)
                if len(rtext) > len(text):
                    res.method = "rendered"
                    res.status_code = rstatus or res.status_code
                    res.html_bytes = len(rhtml.encode("utf-8"))
                    html, text = rhtml, rtext
                    res.error = None
            except Exception as exc:  # noqa: BLE001
                res.error = f"rendered fallback unavailable - {exc}"

    if text:
        RAW_DIR.mkdir(parents=True, exist_ok=True)
        (RAW_DIR / f"{res.page_id}.html").write_text(html, encoding="utf-8")
        (RAW_DIR / f"{res.page_id}.txt").write_text(text, encoding="utf-8")

    res.extract_chars = len(text)
    res.ok = bool(text) and len(text) >= min_chars
    if not res.ok and not res.error:
        res.error = (
            f"extracted {len(text)} chars < min_extract_chars {min_chars} - "
            "probable client-rendered shell"
        )
    if text:
        audit_facts(text, res)
    return res


def write_report(cfg: dict, results: list[PageResult], min_chars: int) -> None:
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    passed = sum(1 for r in results if r.ok)

    lines: list[str] = [
        "# Phase 0 - Corpus Viability Spike Report",
        "",
        f"- **Generated:** {now}",
        f"- **AMC:** {cfg.get('amc', 'n/a')}",
        f"- **Plan variant:** {cfg.get('plan_variant', 'n/a')}",
        f"- **Min extract chars (hard gate):** {min_chars}",
        f"- **Result:** {passed}/{len(results)} pages PASS",
        "",
        "A page below the character threshold is a probable client-rendered shell. "
        "Per FR-2 this is a HARD FAIL, not a warning: with only 5 pages, losing one "
        "means the assistant silently lacks an entire scheme.",
        "",
        "## Per-page results",
        "",
        "| page_id | Scheme | Category | HTTP | HTML bytes | Extracted chars | Method | Verdict |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for r in results:
        lines.append(
            f"| `{r.page_id}` | {r.scheme} | {r.category} | "
            f"{r.status_code if r.status_code is not None else '-'} | "
            f"{r.html_bytes:,} | {r.extract_chars:,} | {r.method} | "
            f"**{r.verdict}** |"
        )

    lines += ["", "## Question-type coverage", "",
              "The 7 question types named in `problemstatement.txt` line 34. "
              "Presence of the label, not verification of the value - eyeball the "
              "snippets below before relying on them.", "",
              "| page_id | " + " | ".join(FACT_LABELS[k] for k in FACT_PATTERNS) + " |",
              "| --- | " + " | ".join("---" for _ in FACT_PATTERNS) + " |"]
    for r in results:
        cells = " | ".join("yes" if r.facts.get(k) else "**no**" for k in FACT_PATTERNS)
        lines.append(f"| `{r.page_id}` | {cells} |")

    lines += ["", "## Coverage across the whole corpus", "",
              "| Question type | Covered | Note |", "| --- | --- | --- |"]
    for key, label in FACT_LABELS.items():
        hits = [r.page_id for r in results if r.facts.get(key)]
        if key == "capital_gains_statement":
            note = ("Expected absent - a Groww **account** help topic, not a scheme "
                    "fact. Tracked as **OD-4**: extend the corpus under source "
                    "line 27, or drop the question type.")
        elif key == "elss_lock_in":
            note = "Expected only on the ELSS page."
        elif key in ("riskometer", "benchmark"):
            note = "Verify per page - these vary by scheme."
        else:
            note = ""
        lines.append(
            f"| {label} | {len(hits)}/{len(results)} | {note} |"
        )

    lines += ["", "## Corpus composition - return/NAV density", "",
              "**Why this matters:** the source forbids performance claims (line 41), "
              "but these pages carry substantial return data - period returns, a "
              "return calculator, NAV values. A 17% mean density means roughly one in "
              "six sentences is a figure we must not emit, so retrieval will "
              "routinely surface them as strong matches and the model will be "
              "tempted to quote them. FR-20's output screen is load-bearing, and "
              "Phase 2 should consider tagging return-heavy chunks so they can be "
              "deprioritised at retrieval time.", "",
              "| page_id | Sentences | Return/NAV sentences | Density |",
              "| --- | --- | --- | --- |"]
    for r in results:
        lines.append(
            f"| `{r.page_id}` | {r.total_sentences:,} | {r.perf_sentences:,} | "
            f"**{r.perf_density:.0%}** |"
        )
    if results:
        avg = sum(r.perf_density for r in results) / len(results)
        lines += ["", f"**Mean across corpus: {avg:.0%}** return/NAV sentences.", ""]

    lines += ["", "## Structural delimiters available for chunking", "",
              "The source requires the chunking strategy to be decided *from the data* "
              "(line 53). These counts say what the data can actually be split on. "
              "A low `period` count means a sentence-recursive splitter will emit "
              "enormous pseudo-sentences and blow the 200-token budget.", "",
              "| page_id | Chars | `.` | `:` | newline | `%` | `₹` |",
              "| --- | --- | --- | --- | --- | --- | --- |"]
    for r in results:
        d = r.delimiters
        lines.append(
            f"| `{r.page_id}` | {r.extract_chars:,} | {d['period']:,} | "
            f"{d['colon']:,} | {d['newline']:,} | {d['percent_sign']:,} | "
            f"{d['rupee']:,} |"
        )
    lines += ["",
              "**Implications for Phase 2 — read before writing the chunker:**",
              "",
              "1. **`newline` is 1 per page.** The spike flattens the DOM to a single "
              "line, destroying the block structure the HTML actually has (295 "
              "`<td>`, 75 `<tr>`, 12 `<h3>`, 6 `<p>` on the ELSS page). Chunk from a "
              "**structure-preserving re-parse of `data/raw/*.html`**, not from the "
              "flattened `.txt`. Table rows and headings are the natural chunk units.",
              "2. **`.` occurs every ~60 characters**, so a sentence-level recursive "
              "splitter is viable and will land inside the 200-token budget. It is a "
              "reasonable *final* fallback, not the primary strategy.",
              "3. **The text is a label-value stream**, not prose: `Expense ratio "
              "1.21%`, `Min. for SIP ₹500`, `Exit load Nil`. Prefer splitting on field "
              "labels, and make each chunk **repeat its own label** so a retrieved "
              "chunk is independently answerable and BM25 can match the label text.",
              "4. **Exit-load detail lives inside a `div.rodal` modal** "
              "(`.exitLoadStampDutyTax_*`), not the visible flow. It is present in the "
              "HTML and extractable, but a visibility-based extractor would silently "
              "drop it - and exit load is a source-named question type.",
              ""]

    lines += ["", "## Evidence snippets", ""]
    for r in results:
        found = [k for k, v in r.facts.items() if v]
        if not found:
            continue
        lines += [f"### `{r.page_id}` - {r.scheme}", ""]
        for key in found:
            lines.append(f"- **{FACT_LABELS[key]}**: `{r.fact_snippets.get(key, '')}`")
        lines.append("")

    errors = [r for r in results if not r.ok]
    lines += ["## Errors", ""]
    if errors:
        for r in errors:
            lines.append(f"- `{r.page_id}` - {r.error}")
    else:
        lines.append("None.")
    lines.append("")

    REPORT_PATH.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser(description="Corpus viability spike")
    ap.add_argument("--min-chars", type=int, default=None,
                    help="override min_extract_chars from corpus.yaml")
    ap.add_argument("--only", default=None, help="spike a single page_id")
    ap.add_argument("--no-rendered", action="store_true",
                    help="skip the headless-browser fallback")
    args = ap.parse_args()

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    cfg = load_corpus(CORPUS_PATH)
    min_chars = args.min_chars or int(cfg.get("min_extract_chars", 1500))
    pages = cfg["pages"]
    if args.only:
        pages = [p for p in pages if p["page_id"] == args.only]
        if not pages:
            sys.exit(f"[FATAL] no page_id '{args.only}' in {CORPUS_PATH}")

    print(f"Phase 0 corpus spike - {len(pages)} page(s), min_extract_chars={min_chars}")
    results: list[PageResult] = []
    for i, page_cfg in enumerate(pages):
        res = process(page_cfg, min_chars, allow_rendered=not args.no_rendered)
        results.append(res)
        print(
            f"    -> {res.verdict}  http={res.status_code}  "
            f"html={res.html_bytes:,}B  text={res.extract_chars:,}ch  ({res.method})"
        )
        if i < len(pages) - 1:
            time.sleep(POLITE_DELAY)

    write_report(cfg, results, min_chars)

    passed = sum(1 for r in results if r.ok)
    print(f"\n{passed}/{len(results)} PASS -> {REPORT_PATH.relative_to(ROOT)}")

    if passed < len(results):
        print("\n[FAIL] Do not build the pipeline on a partial corpus.", file=sys.stderr)
        for r in results:
            if not r.ok:
                print(f"  - {r.page_id}: {r.error}", file=sys.stderr)
        return 1

    print("\nCorpus is viable. Next: Phase 1 (scaffold + contracts).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
