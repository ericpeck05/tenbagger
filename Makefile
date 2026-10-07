.PHONY: setup dev test lint format load bulk filings coverage demo demo-reset

PY := backend/.venv/bin/python
URL := http://localhost:5173

# Install backend and frontend dependencies and the secret-scanning git hook.
setup: backend/.venv/.installed frontend/node_modules/.installed
	@git config core.hooksPath .githooks
	@test -f .env || (cp .env.example .env && chmod 600 .env && echo "Created .env from .env.example")

backend/.venv/.installed: backend/pyproject.toml
	python3 -m venv backend/.venv
	$(PY) -m pip install -q --upgrade pip
	$(PY) -m pip install -q -e "backend[dev]"
	@touch $@

frontend/node_modules/.installed: frontend/package.json frontend/package-lock.json
	cd frontend && npm ci --silent
	@touch $@

# Start the API on :8000 and the UI on :5173, then open the browser. Ctrl-C stops both.
dev: setup
	@trap 'kill 0' INT TERM EXIT; \
	(cd backend && .venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload) & \
	(cd frontend && npm run -s dev) & \
	(for i in $$(seq 1 40); do curl -sf $(URL) >/dev/null && break; sleep 0.25; done; open $(URL) 2>/dev/null || xdg-open $(URL) 2>/dev/null || true) & \
	wait

test: setup
	cd backend && .venv/bin/pytest -q
	cd frontend && npm run -s typecheck

lint: setup
	cd backend && .venv/bin/ruff check . && .venv/bin/ruff format --check .
	cd frontend && npm run -s lint

format: setup
	cd backend && .venv/bin/ruff check --fix . && .venv/bin/ruff format .

# Load S&P 500 fundamentals from EDGAR (about two minutes), then report tag coverage.
load: setup
	cd backend && .venv/bin/python -m app.jobs.load_sp500

# Load every listed US company from EDGAR's nightly bulk files (3 GB download, about 15 minutes).
bulk: setup
	cd backend && .venv/bin/python -m app.jobs.bulk_load

# Pick up filings since the last run (the app also does this twice a day).
filings: setup
	cd backend && .venv/bin/python -m app.jobs.refresh_filings

coverage: setup
	cd backend && .venv/bin/python -m app.jobs.coverage

# Run on bundled sample data: real EDGAR fundamentals for ten companies, made-up prices and
# portfolio. No keys, no network calls. Uses its own ports and database, so it can run
# next to `make dev`.
DEMO_ENV := DATA_DIR=$(CURDIR)/data/demo DEMO=true RUN_JOBS=false \
	FINNHUB_API_KEY= ALPACA_KEY_ID= ALPACA_SECRET_KEY= SEC_USER_AGENT=
DEMO_URL := http://localhost:5174

demo: setup
	cd backend && $(DEMO_ENV) .venv/bin/python -m app.demo.build --if-missing
	@trap 'kill 0' INT TERM EXIT; \
	(cd backend && $(DEMO_ENV) .venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8100) & \
	(cd frontend && PORT=5174 API_PORT=8100 npm run -s dev) & \
	(for i in $$(seq 1 40); do curl -sf $(DEMO_URL) >/dev/null && break; sleep 0.25; done; open $(DEMO_URL) 2>/dev/null || xdg-open $(DEMO_URL) 2>/dev/null || true) & \
	wait

demo-reset:
	rm -rf data/demo
