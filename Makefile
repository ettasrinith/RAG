.PHONY: dev test lint typecheck format clean install docker-up docker-down

PYTHON := python
PIP := pip

dev:
	$(PYTHON) -m uvicorn api.server:app --reload --port 8000

test:
	$(PYTHON) -m pytest tests/ -v --cov=core --cov=api --cov=services

test-fast:
	$(PYTHON) -m pytest tests/ -x -q --no-header

lint:
	$(PYTHON) -m ruff check .
	$(PYTHON) -m ruff format --check .

format:
	$(PYTHON) -m ruff check --fix .
	$(PYTHON) -m ruff format .

typecheck:
	$(PYTHON) -m mypy core/ api/ services/ --ignore-missing-imports

security:
	$(PYTHON) -m bandit -r core/ api/ services/ -x tests/

clean:
	find . -type d -name __pycache__ -exec rm -rf {} +
	find . -type f -name "*.pyc" -delete

docker-up:
	docker compose up --build

docker-down:
	docker compose down
