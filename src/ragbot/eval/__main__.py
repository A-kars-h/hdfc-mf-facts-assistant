"""`python -m src.ragbot.eval` - run the sample set and report M-1..M-7.

Equivalent to `python -m src.ragbot.eval.runner`. The bare package entry point
exists because `make eval` should be a memorable command, and because the
calibration step has to be runnable on its own too - see
`python -m src.ragbot.eval.calibrate`.
"""

from __future__ import annotations

from .runner import main

if __name__ == "__main__":
    raise SystemExit(main())
