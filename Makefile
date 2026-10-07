.PHONY: setup dev test lint format load coverage demo

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
	(for i in $$(seq 1 40); do curl -sf $(URL) >/dev/null && break; sleep 0.25; done; open $(URL)) & \
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

coverage: setup
	cd backend && .venv/bin/python -m app.jobs.coverage

demo:
	@echo "Demo mode arrives in phase 7."
	@exit 1
