"""Ad-hoc inspection helper for the Phase 0 extracts (not part of the pipeline)."""
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parent.parent
NAV_PHRASES = [
    "Invest in Stocks", "ETF Screener", "Share Market Today", "Stock Events",
    "Demat Account", "Open an account", "Intraday", "Option chain",
]

for name in ("hdfc-elss", "hdfc-large-cap"):
    path = ROOT / "data" / "raw" / f"{name}.txt"
    text = path.read_text(encoding="utf-8")
    print(f"=== {name}  ({len(text):,} chars) ===")
    print("--- first 600 chars ---")
    print(text[:600])
    print("--- nav leakage ---")
    leaks = [p for p in NAV_PHRASES if p in text]
    print("  LEAKED:" if leaks else "  none", leaks)
    print()
