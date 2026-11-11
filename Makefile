# make check: tests and the leak scan, locally. make ship: check, push main, smoke-test a fresh clone,
# and revert the push if the smoke test fails.
.PHONY: check test scan ship

PY ?= python3

check: test scan

test:
	$(PY) -m unittest discover -s tests

scan:
	$(PY) scripts/leak_scan.py

ship: check
	@test -z "$$(git status --porcelain)" || { echo "ship: commit or drop local changes first"; exit 1; }
	@test "$$(git symbolic-ref --short HEAD)" = main || { echo "ship: run from main"; exit 1; }
	@bash scripts/ship.sh
