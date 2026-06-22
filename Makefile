# Mesaar Logistics Operations API — developer task runner.
#
# Usage: `make <target>`. Run `make help` to list targets.

# Use bash for recipe execution.
SHELL := /bin/bash

# Override on the command line, e.g. `make run PORT=9000`.
PYTHON ?= python
PORT ?= 8000
HOST ?= 0.0.0.0
APP ?= app.main:app
CELERY_APP ?= app.workers.celery_app
MSG ?= update

.DEFAULT_GOAL := help

.PHONY: help run worker beat migrate revision test lint fmt up down logs

help: ## Show this help message.
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
		| awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-12s\033[0m %s\n", $$1, $$2}'

run: ## Run the API locally with autoreload (uvicorn).
	$(PYTHON) -m uvicorn $(APP) --reload --host $(HOST) --port $(PORT)

worker: ## Start a Celery worker.
	$(PYTHON) -m celery -A $(CELERY_APP) worker --loglevel=info

beat: ## Start the Celery beat scheduler.
	$(PYTHON) -m celery -A $(CELERY_APP) beat --loglevel=info

migrate: ## Apply all database migrations (alembic upgrade head).
	$(PYTHON) -m alembic upgrade head

revision: ## Autogenerate a migration revision (make revision MSG="describe change").
	$(PYTHON) -m alembic revision --autogenerate -m "$(MSG)"

test: ## Run the test suite.
	$(PYTHON) -m pytest -q

lint: ## Lint the codebase (ruff + black --check).
	$(PYTHON) -m ruff check app
	$(PYTHON) -m black --check -l 100 app

fmt: ## Auto-format the codebase (ruff --fix + black).
	$(PYTHON) -m ruff check --fix app
	$(PYTHON) -m black -l 100 app

up: ## Build and start the full stack via docker compose.
	docker compose up --build -d

down: ## Stop and remove the docker compose stack.
	docker compose down

logs: ## Tail logs from all docker compose services.
	docker compose logs -f
