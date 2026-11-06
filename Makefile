# Common tasks. `make` builds; `make test` runs everything CI runs.
PY ?= python3
SWEEP_DATE ?= 2026-11-06

.PHONY: build check test unit verify install clean

build:
	$(PY) build_calendar.py

check:
	$(PY) build_calendar.py --check

unit:
	$(PY) -m pytest -q

verify:
	$(PY) build_calendar.py --today $(SWEEP_DATE) --out /tmp/anime-calendar-verify.html
	node verify.js /tmp/anime-calendar-verify.html $(SWEEP_DATE)

test: unit check verify

install:
	pip install -r requirements.txt
	npm ci

clean:
	rm -rf __pycache__ tests/__pycache__ .pytest_cache
