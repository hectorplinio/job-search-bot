# The project's commands in one place, so CI runs exactly what you run. If a
# check changes, change it here and CI inherits it.
#
# Windows does not ship `make`: install it with `winget install GnuWin32.Make`
# or `choco install make`, or copy the recipe you need by hand.

PYTHON ?= python
PACKAGES = src tests

.DEFAULT_GOAL := help
.PHONY: help install install-dev lint types format format-check test test-cov check config-check run dry-run bot clean

help:  ## List the available commands
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
		| awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-14s\033[0m %s\n", $$1, $$2}'

install:  ## Install the bot
	$(PYTHON) -m pip install -e .

install-dev: install  ## Install the development tools too
	$(PYTHON) -m pip install -r requirements-dev.txt

lint:  ## ruff + flake8
	$(PYTHON) -m ruff check $(PACKAGES)
	$(PYTHON) -m flake8 $(PACKAGES)

types:  ## Type checking with mypy
	$(PYTHON) -m mypy

format:  ## Format with black
	$(PYTHON) -m black $(PACKAGES)

format-check:  ## Fail if anything is unformatted
	$(PYTHON) -m black --check $(PACKAGES)

test:  ## Tests (they never touch the network)
	$(PYTHON) -m pytest -q

test-cov:  ## Tests with a coverage report
	$(PYTHON) -m pytest -q --cov=src/jobbot --cov-report=term-missing

config-check:  ## Check that the criteria and the profiles load
	@$(PYTHON) -c "from jobbot.domain.criteria import Criteria; \
		from jobbot.domain.profile import CandidateProfile; \
		[print(r, '->', len(Criteria.load(r).search.queries), 'searches') \
		 for r in ('config.yaml', 'examples/frontend/config.yaml')]; \
		[print(r, '->', CandidateProfile.load(r).name) \
		 for r in ('profile/cv.yaml', 'examples/frontend/cv.yaml')]"

check: lint types format-check test config-check  ## Everything CI runs

run:  ## One real search
	$(PYTHON) -m jobbot.cli run

dry-run:  ## A search that sends nothing and spends nothing on the LLM
	$(PYTHON) -m jobbot.cli run --dry-run --no-llm

bot:  ## Start the bot listening on Telegram
	$(PYTHON) -m jobbot.cli bot

clean:  ## Remove caches and build artefacts
	$(PYTHON) -c "import pathlib, shutil; \
		[shutil.rmtree(p, ignore_errors=True) for p in pathlib.Path('.').rglob('__pycache__')]; \
		[shutil.rmtree(p, ignore_errors=True) for p in ('.pytest_cache', '.ruff_cache', 'build', 'dist', 'htmlcov')]"
