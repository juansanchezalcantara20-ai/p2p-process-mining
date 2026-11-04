# One command reproduces everything:  make all
PY ?= python

.PHONY: install data all sample synthetic test lint docs serve clean

install:            ## install the package with dev + docs extras
	$(PY) -m pip install -e ".[dev,docs]"

data:               ## download (or locate) the BPI Challenge 2019 log
	$(PY) -c "from p2pmining import ingest; print(ingest.locate_raw())"

all: install data   ## full pipeline on the complete log + build the report site
	$(PY) -m p2pmining.pipeline --source full
	mkdocs build --strict

sample:             ## same pipeline on the versioned 1% stratified sample (fast)
	$(PY) -m p2pmining.pipeline --source sample

synthetic:          ## Plan C: seeded synthetic log with injected problems
	$(PY) -m p2pmining.pipeline --source synthetic

test:
	$(PY) -m pytest

lint:
	ruff check . && ruff format --check .

docs:
	mkdocs build --strict

serve:
	mkdocs serve

clean:
	rm -rf build site data/interim/*.parquet
