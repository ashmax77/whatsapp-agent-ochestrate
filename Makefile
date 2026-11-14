.PHONY: dev ingest validate-kb test eval

PYTHON ?= brain/.venv/Scripts/python.exe
SUITE ?= all
OFFLINE ?= 1

ifeq ($(OFFLINE),1)
EVAL_FLAGS := --offline
else
EVAL_FLAGS :=
endif

dev:
	cd brain && uvicorn app.main:app --reload --port 8000

ingest:
	cd brain && $(notdir $(PYTHON)) -m app.rag.ingest --rebuild

validate-kb:
	cd brain && $(notdir $(PYTHON)) -m app.rag.validate_kb

test:
	cd brain && $(notdir $(PYTHON)) -m unittest discover -s tests -v

eval:
	cd brain && $(notdir $(PYTHON)) -m eval.run --suite $(SUITE) $(EVAL_FLAGS)

retention:
	cd brain && $(notdir $(PYTHON)) -m app.db.retention

load-test:
	cd brain && $(notdir $(PYTHON)) -m eval.load_test --concurrency 20

docker-build:
	docker compose build


