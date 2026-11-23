# Optional workspace shortcuts. Each application also works on its own.
PYTHON ?= python
.PHONY: install run worker beat migrate test lint typecheck frontend up down logs
install run worker beat migrate test lint typecheck:
	$(MAKE) -C logistic-x-backend $@ PYTHON=$(PYTHON)
frontend:
	cd logistic-x-frontend && npm run dev
up:
	docker compose up --build -d
down:
	docker compose down
logs:
	docker compose logs -f
