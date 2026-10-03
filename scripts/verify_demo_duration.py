"""Read an MP4's duration from its header without downloading the whole file.

Purpose: PRD §18 requires the demo to be <= 3 minutes. The deliverable is a
355 MB Drive file, so rather than assert the duration from the filename, read it
from the `mvhd` atom using HTTP range requests - about 1 MB of the file.

No product code is touched. Nothing is written except the printed result.

Usage:  python scripts/verify_demo_duration.py <drive-file-id>
"""

from __future__ import annotations

import re
import struct
import sys
from urllib.parse import urlencode

import httpx

CHUNK = 4 << 20  # 4 MiB. moov sits ~1.1 MB from EOF on this file; 1 MiB missed it.


def _confirm_url(file_id: str) -> str:
    """Drive gates large public files behind an interstitial confirm token.

    The interstitial is a GET form whose only hidden fields are `confirm=t` and a
    per-session `uuid`; the download link itself is built by a JS-free form submit,
    so there is no href to scrape.
    """
    page = httpx.get(
        f"https://drive.usercontent.google.com/download?id={file_id}&export=download",
        follow_redirects=True,
        timeout=60.0,
    )
    if "uc-download-link" not in page.text:
        raise SystemExit(
            "no download form found - the file is probably NOT shared publicly"
        )
    params = {"id": file_id, "export": "download"}
    for name in ("confirm", "uuid"):
        found = re.search(rf'name="{name}"\s+value="([^"]+)"', page.text)
        if not found:
            raise SystemExit(f"interstitial is missing the {name!r} token")
        params[name] = found.group(1)
    return "https://drive.usercontent.google.com/download?" + urlencode(params)


def _walk(buf: bytes, start: int, end: int, want: bytes):
    """Yield (type, payload_start, payload_end) for atoms in [start, end)."""
    pos = start
    while pos + 8 <= end:
        (size,) = struct.unpack_from(">I", buf, pos)
        kind = buf[pos + 4 : pos + 8]
        if size == 1:
            (size,) = struct.unpack_from(">Q", buf, pos + 8)
            header = 16
        else:
            header = 8
        if size == 0:
            size = end - pos
        payload = pos + header
        stop = min(pos + size, end)
        if stop <= payload:
            return
        if kind == want:
            yield kind, payload, stop
        # Only recurse into the container atoms that can hold moov.
        if kind in (b"moov", b"trak", b"mdia", b"minf", b"stbl"):
            yield from _walk(buf, payload, stop, want)
        pos += size


def _duration_from_mvhd(buf: bytes) -> float | None:
    """Parse the first `mvhd` atom found anywhere in the buffer.

    Scanning for the atom type rather than walking the atom tree is deliberate:
    when the header slice comes from the tail of the file there is no guarantee
    it begins on an atom boundary, but `mvhd` is unambiguous and its payload is
    fixed-layout, so the duration is still exactly readable.
    """
    at = buf.find(b"mvhd")
    if at < 0:
        return None
    base = at + 4  # skip the 4-byte type
    version = buf[base]
    if version == 0:
        timescale, duration = struct.unpack_from(">II", buf, base + 12)
    else:
        timescale, duration = struct.unpack_from(">IQ", buf, base + 20)
    if not timescale:
        return None
    return duration / timescale


def main() -> int:
    file_id = sys.argv[1]
    url = _confirm_url(file_id)

    # One byte from the front reveals the total size via Content-Range.
    probe = httpx.get(url, headers={"Range": "bytes=0-0"}, follow_redirects=True, timeout=120.0)
    cr = probe.headers.get("content-range", "")
    if "/" not in cr:
        raise SystemExit(f"no Content-Range; cannot size the file (got {cr!r})")
    total = int(cr.rsplit("/", 1)[1])
    print(f"file size = {total / 1e6:.0f} MB")

    # moov sits at the front in a well-formed MP4, at the back when the recorder
    # streamed the mdat first. Try both.
    for label, start, length in (
        ("head", 0, min(CHUNK, total)),
        ("tail", max(0, total - CHUNK), CHUNK),
    ):
        end = min(start + length, total) - 1
        got = httpx.get(
            url,
            headers={"Range": f"bytes={start}-{end}"},
            follow_redirects=True,
            timeout=120.0,
        )
        print(f"{label}: fetched {len(got.content)} bytes, status {got.status_code}")
        seconds = _duration_from_mvhd(got.content)
        if seconds is None:
            continue
        print(f"timescale/duration read from the {label}")
        print(f"DURATION = {seconds:.2f} s = {int(seconds // 60)}m {seconds % 60:04.1f}s")
        print("WITHIN 3 MINUTE LIMIT" if seconds <= 180 else "OVER THE 3 MINUTE LIMIT")
        return 0 if seconds <= 180 else 1

    print("no mvhd atom in the head or tail slice; cannot verify")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())