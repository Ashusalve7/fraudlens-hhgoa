.PHONY: install check test lint frontend dashboard validate clean

install:
	uv sync --project fraudlens --all-groups
	npm ci --prefix fraudlens/dashboard

check:
	uv run --project fraudlens python scripts/secret_scan.py
	uv run --project fraudlens python scripts/check_dataset.py

test:
	uv run --project fraudlens pytest fraudlens/tests

lint:
	uv run --project fraudlens ruff check fraudlens scripts

frontend:
	npm run build --prefix fraudlens/dashboard

validate:
	uv run --project fraudlens python fraudlens/validator.py

dashboard:
	uv run --project fraudlens uvicorn dashboard.app:app --app-dir fraudlens --host 127.0.0.1 --port 8000

clean:
	find fraudlens -type d -name __pycache__ -prune -exec rm -rf {} +
	rm -rf fraudlens/.pytest_cache fraudlens/.ruff_cache .pytest_cache .ruff_cache
