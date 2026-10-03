# ragbot task runner.
#
# NOTE ON `make` AVAILABILITY
# ----------------------------
# `make` is NOT installed on the machine this was built on (Windows, no GNU
# make, no git-bash make). Every recipe below is therefore a plain command that
# can be run directly. If `make` is unavailable to you too, read this file and
# run the command under the target you need - that is what `make` does anyway.
#
# Phases are additive: `ingest` needs `fetch`, and so on. `make help` lists them.

PYTHON ?= python
SRC    := src

# The venv interpreter lives in a different place on Windows, and `rm`/`find`
# do not exist there. Resolve the path once and use Python for the recursive
# deletes so every target runs on both platforms.
ifeq ($(OS),Windows_NT)
VENV_PY := .venv/Scripts/python.exe
else
VENV_PY := .venv/bin/python
endif

.DEFAULT_GOAL := help
.PHONY: help setup fetch ingest run eval calibrate test lint clean all deliverables

help:  ## Show this help
	@echo "ragbot targets:"
	@echo "  make setup      - create .venv, install Phase 1 dependencies"
	@echo "  make fetch      - Phase 0: fetch + extract the 5 corpus pages"
	@echo "  make ingest     - Phase 2: chunk, embed, build Chroma + BM25 + manifest"
	@echo "  make run        - Phase 7: launch the Streamlit UI"
	@echo "  make eval       - Phase 6: run the golden set and print metrics"
	@echo "  make calibrate  - Phase 6: derive SIMILARITY_THRESHOLD, write calibration.json"
	@echo "  make test       - run the test suite"
	@echo "  make deliverables - Phase 8: regenerate source_list, sample_qa, screenshots"
	@echo "  make all        - fetch + ingest + eval"
	@echo ""
	@echo "Done-when check for Phase 1:"
	@echo "  $(PYTHON) -c \"from src.ragbot.core import config, models, errors\""

setup:  ## Create the venv and install all pinned dependencies
	$(PYTHON) -m venv .venv
	$(VENV_PY) -m pip install --upgrade pip
	$(VENV_PY) -m pip install torch==2.14.0 --index-url https://download.pytorch.org/whl/cpu
	$(VENV_PY) -m pip install -r requirements.txt
	@echo "Now: copy .env.example to .env and fill in what you need."

fetch:  ## Phase 0: fetch and extract the corpus into data/raw
	$(PYTHON) scripts/spike_fetch.py

ingest:  ## Phase 2: chunk, embed, and build the indexes
	$(PYTHON) -m src.ragbot.ingest --reindex

run:  ## Phase 7: launch the Streamlit UI
	$(PYTHON) -m streamlit run src/ragbot/ui/app.py --server.address 127.0.0.1

eval:  ## Phase 6: evaluate against the golden set
	$(PYTHON) -m src.ragbot.eval

calibrate:  ## Phase 6: derive the gate threshold from the sample set
	$(PYTHON) -m src.ragbot.eval.calibrate

test:  ## Run the test suite
	$(PYTHON) -m pytest tests -q

all: fetch ingest eval  ## fetch, ingest, then evaluate

# Phase 8 deliverables that are GENERATED rather than written by hand.
#   D-2 source list (csv + md), D-4 sample Q&A (from a real eval run),
#   and the UI text renders under artifacts/screenshots/.
# artifacts/demo_script.md and artifacts/disclaimer_snippet.md are prose and are
# maintained by hand, not generated.
deliverables:  ## Phase 8: regenerate the generated deliverables
	$(PYTHON) scripts/phase8_source_list.py
	$(PYTHON) scripts/phase8_eval_capture.py
	$(PYTHON) scripts/phase8_sample_qa.py
	$(PYTHON) scripts/phase8_screenshots.py

clean:  ## Remove generated indexes and caches (keeps data/raw)
	$(PYTHON) -c "import shutil,pathlib; [shutil.rmtree(p, ignore_errors=True) for p in ('data/chroma','.pytest_cache')]; [p.unlink() for p in (pathlib.Path('data/bm25.pkl'),pathlib.Path('artifacts/manifest.json')) if p.exists()]; [shutil.rmtree(d, ignore_errors=True) for d in pathlib.Path('.').rglob('__pycache__')]"
