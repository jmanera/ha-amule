.PHONY: help install lint typecheck test ui-check ha-lint ha-test hassfest security check dev demo amuled image clean

UV ?= uv
HA_UV ?= uv --directory integration_tests
IMAGE ?= ha-amule:dev

help:  ## Show this help
	@grep -E '^[a-z0-9-]+:.*##' $(MAKEFILE_LIST) | awk -F':.*## ' '{printf "  %-12s %s\n", $$1, $$2}'

install:  ## Install dependencies and git hooks
	$(UV) sync --frozen
	$(HA_UV) sync --frozen
	$(UV) run pre-commit install

lint:  ## Ruff lint + format check
	$(UV) run ruff check src tests scripts
	$(UV) run ruff format --check src tests scripts

typecheck:  ## mypy --strict
	$(UV) run mypy src

test:  ## App tests with coverage gate
	$(UV) run pytest --cov --cov-report=term

ui-check:  ## Syntax-check the web UI
	node --check src/ha_amule/static/app.js

ha-lint:  ## Ruff + mypy --strict for the Home Assistant integration (Python 3.14 env)
	$(HA_UV) run ruff check ../custom_components tests
	$(HA_UV) run ruff format --check ../custom_components tests
	$(HA_UV) run mypy ../custom_components/amule

ha-test:  ## Integration tests against a real Home Assistant core
	$(HA_UV) run pytest -p no:cacheprovider --cov --cov-report=term

hassfest:  ## Home Assistant's official integration validator (Docker)
	docker run --rm -v "$(CURDIR):/github/workspace" ghcr.io/home-assistant/hassfest

security:  ## bandit + pip-audit
	$(UV) run bandit -q -r src
	$(UV) export --frozen --no-dev --no-emit-project -o .audit-requirements.txt >/dev/null
	$(UV) run pip-audit -r .audit-requirements.txt --disable-pip
	@rm -f .audit-requirements.txt

check: lint typecheck test ui-check ha-lint ha-test security  ## Everything. Runs locally, not in CI

dev:  ## App on :8099 against your own amuled (AMULE_EC_HOST, AMULE_EC_PORT, AMULE_EC_PASSWORD)
	AMULE_EC_HOST=$${AMULE_EC_HOST:-127.0.0.1} AMULE_DATA_DIR=.data $(UV) run ha-amule

demo:  ## App on http://localhost:8099 with a fake amuled and canned data
	$(UV) run python scripts/fake_amuled.py & echo $$! > .fake_amuled.pid; \
	trap 'kill $$(cat .fake_amuled.pid); rm -f .fake_amuled.pid' EXIT INT TERM; \
	AMULE_EC_HOST=127.0.0.1 AMULE_EC_PORT=14713 AMULE_EC_PASSWORD=demo AMULE_DATA_DIR=.data \
		$(UV) run ha-amule

amuled:  ## A real amuled in Docker on 127.0.0.1:4712 (password "dev") for `make dev`
	docker build -q -t ha-amule:dev -f amule/Dockerfile . >/dev/null
	docker run --rm -it -p 127.0.0.1:4712:4712 -e AMULE_REMOTE_PASSWORD=dev -e AMULE_INGRESS_ONLY=false ha-amule:dev

image:  ## Build the app image for this machine
	docker build -f amule/Dockerfile -t $(IMAGE) .

clean:
	rm -rf dist .data .pytest_cache .mypy_cache .ruff_cache .coverage coverage.xml htmlcov
