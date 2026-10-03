"""Ensure raw HTML exists for every corpus page.

Reuses `data/raw/*.html` when present. That is not just a speed optimisation:
it makes an ingest run deterministic and offline-capable, so the manifest's
`content_hash` reflects a known HTML state and a re-run after a site redesign
cannot silently change the index.

Phase 0 already proved all 5 pages are server-rendered, so a plain `httpx` GET
suffices and no headless browser is needed.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import httpx

from ..core.config import Settings, get_settings
from ..core.errors import PageFetchError
from ..core.logging import get_logger

log = get_logger(__name__)


@dataclass
class RawPage:
    page_id: str
    path: Path
    fetched_at: datetime
    from_cache: bool


def _fetch_one(
    client: httpx.Client, url: str, page_id: str, settings: Settings
) -> tuple[str, datetime]:
    """GET with bounded retries. Retry only transient failures."""
    last: Exception | None = None
    for attempt in range(1, settings.max_retries + 1):
        try:
            response = client.get(url)
            response.raise_for_status()
            if not response.text.strip():
                raise PageFetchError(page_id, f"{url} returned an empty body")
            return response.text, datetime.now(timezone.utc)
        except Exception as exc:  # noqa: BLE001 - re-raised below
            last = exc
            if attempt < settings.max_retries:
                delay = 1.5 * attempt
                log.warning(
                    "fetch attempt %d/%d failed page=%s err=%s; retrying in %.1fs",
                    attempt, settings.max_retries, page_id, exc, delay,
                )
                time.sleep(delay)
    raise PageFetchError(
        f"{page_id}: could not fetch {url} after {settings.max_retries} attempts: {last}"
    )


def ensure_raw_pages(
    pages: list[dict], settings: Settings | None = None, *, refresh: bool = False
) -> list[RawPage]:
    """Return a RawPage per corpus entry, fetching only what is missing.

    `fetched_at` comes from the file's mtime when cached, so the value recorded
    in the manifest reflects when the bytes were actually retrieved. Recording
    "now" for a cached file would make `Last updated from sources:` a lie -
    the single most likely way for this project to state something false about
    its own data.
    """
    settings = settings or get_settings()
    raw_dir = settings.raw_dir_abs
    raw_dir.mkdir(parents=True, exist_ok=True)

    out: list[RawPage] = []
    to_fetch: list[dict] = []

    for page in pages:
        path = raw_dir / f"{page['page_id']}.html"
        if path.exists() and path.stat().st_size > 0 and not refresh:
            out.append(
                RawPage(
                    page_id=str(page["page_id"]),
                    path=path,
                    fetched_at=datetime.fromtimestamp(path.stat().st_mtime, timezone.utc),
                    from_cache=True,
                )
            )
        else:
            to_fetch.append(page)

    if to_fetch:
        log.info("fetching %d page(s) from network", len(to_fetch))
        with httpx.Client(
            timeout=30.0,
            follow_redirects=True,
            headers={"User-Agent": settings.user_agent, "Accept-Language": "en-IN,en;q=0.9"},
        ) as client:
            for page in to_fetch:
                text, when = _fetch_one(
                    client, str(page["source_url"]), str(page["page_id"]), settings
                )
                path = raw_dir / f"{page['page_id']}.html"
                path.write_text(text, encoding="utf-8")
                log.info(
                    "fetched page=%s bytes=%d", page["page_id"], len(text.encode("utf-8"))
                )
                out.append(RawPage(str(page["page_id"]), path, when, from_cache=False))

    order = {str(p["page_id"]): i for i, p in enumerate(pages)}
    out.sort(key=lambda r: order.get(r.page_id, 0))
    return out
