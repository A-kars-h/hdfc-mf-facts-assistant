"""Phase 8: generate D-2, the source list, as CSV **and** MD.

Both files are derived from `config/corpus.yaml` (which pages exist) joined with
`artifacts/manifest.json` (when each was fetched). Nothing is typed in, and no
URL appears that is not in the corpus definition - invariant 10. The educational
link table is read from `config/education_links.yml`; when that map is empty,
which it ships, the file says so rather than showing a plausible-looking row.

Usage:  python scripts/phase8_source_list.py
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.ragbot.core.config import load_corpus, load_education_links  # noqa: E402
from src.ragbot.core.config import Settings  # noqa: E402

ART = ROOT / "artifacts"
HEADER = ["page_id", "scheme", "category", "source_url", "fetched_at"]


def _csv_cell(value: str) -> str:
    return '"' + value.replace('"', '""') + '"' if any(c in value for c in ',"\n') else value


def main() -> None:
    settings = Settings()
    corpus = load_corpus(settings)
    manifest = settings.manifest_file
    fetched = {}
    if manifest.exists():
        from src.ragbot.core.models import PageManifest

        for record in PageManifest.model_validate_json(
            manifest.read_text(encoding="utf-8")
        ).pages:
            fetched[record.page_id] = record.fetched_at

    pages = corpus["pages"]

    # --- CSV ---------------------------------------------------------------
    csv_path = ART / "source_list.csv"
    lines = [",".join(HEADER)]
    for page in pages:
        stamp = fetched.get(page["page_id"])
        lines.append(
            ",".join(
                _csv_cell(str(v))
                for v in (
                    page["page_id"],
                    page["scheme"],
                    page["category"],
                    page["source_url"],
                    stamp.isoformat() if stamp else "",
                )
            )
        )
    csv_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    # --- MD ----------------------------------------------------------------
    md: list[str] = [
        "# D-2 Source List",
        "",
        f"Corpus: **{corpus['amc']}**, plan variant **{corpus['plan_variant']}**, "
        f"**{len(pages)} pages**. Generated from `config/corpus.yaml` and "
        "`artifacts/manifest.json` by `scripts/phase8_source_list.py`.",
        "",
        "No URL appears below that is not in the corpus definition.",
        "",
        "| page_id | scheme | category | source_url | fetched_at |",
        "|---|---|---|---|---|",
    ]
    for page in pages:
        stamp = fetched.get(page["page_id"])
        url = page["source_url"]
        md.append(
            f"| `{page['page_id']}` | {page['scheme']} | {page['category']} "
            f"| [{url}]({url}) | {stamp.date().isoformat() if stamp else '-'} |"
        )

    md += ["", "## Educational links (human-verified)", ""]
    links = load_education_links(settings) or {}
    entries = links.get("links") or links.get("entries") or []
    if entries:
        md += ["| topic | url | title | notes |", "|---|---|---|---|"]
        for entry in entries:
            if isinstance(entry, dict):
                topic = entry.get("topic") or entry.get("key") or ""
                url = entry.get("url") or ""
                md.append(
                    f"| {topic} | [{url}]({url}) | {entry.get('title') or ''} "
                    f"| {entry.get('notes') or ''} |"
                )
            else:
                md.append(f"| {entry} | | | |")
    else:
        md += [
            "**None.** `config/education_links.yml` ships an empty map (OD-2), so an",
            "opinion refusal carries `educational_link_missing=True` and the UI says the",
            "link is unavailable rather than inventing a URL. An unverified link is worse",
            "than no link, so none is listed here.",
        ]

    md_path = ART / "source_list.md"
    md_path.write_text("\n".join(md) + "\n", encoding="utf-8")

    print(f"wrote {csv_path}")
    print(f"wrote {md_path}")


if __name__ == "__main__":
    main()