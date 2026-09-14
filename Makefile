# Los comandos del proyecto en un solo sitio, para que la CI ejecute
# exactamente lo mismo que ejecutas tu. Si un check cambia, cambia aqui y la
# CI lo hereda.
#
# En Windows no viene `make`: instalalo con `winget install GnuWin32.Make` o
# `choco install make`, o copia el comando de la receta que necesites.

PYTHON ?= python
PACKAGES = src tests

.DEFAULT_GOAL := help
.PHONY: help install install-dev lint types format format-check test test-cov check config-check run dry-run bot clean

help:  ## Lista los comandos disponibles
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
		| awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-14s\033[0m %s\n", $$1, $$2}'

install:  ## Instala el bot
	$(PYTHON) -m pip install -e .

install-dev: install  ## Instala tambien las herramientas de desarrollo
	$(PYTHON) -m pip install -r requirements-dev.txt

lint:  ## ruff + flake8
	$(PYTHON) -m ruff check $(PACKAGES)
	$(PYTHON) -m flake8 $(PACKAGES)

types:  ## Comprobacion de tipos con mypy
	$(PYTHON) -m mypy

format:  ## Formatea con black
	$(PYTHON) -m black $(PACKAGES)

format-check:  ## Falla si algo esta sin formatear
	$(PYTHON) -m black --check $(PACKAGES)

test:  ## Tests (no tocan la red)
	$(PYTHON) -m pytest -q

test-cov:  ## Tests con informe de cobertura
	$(PYTHON) -m pytest -q --cov=src/jobbot --cov-report=term-missing

config-check:  ## Comprueba que los criterios y los perfiles cargan
	@$(PYTHON) -c "from jobbot.domain.criteria import Criteria; \
		from jobbot.domain.profile import CandidateProfile; \
		[print(r, '->', len(Criteria.load(r).search.queries), 'busquedas') \
		 for r in ('config.yaml', 'examples/frontend/config.yaml')]; \
		[print(r, '->', CandidateProfile.load(r).name) \
		 for r in ('profile/cv.yaml', 'examples/frontend/cv.yaml')]"

check: lint types format-check test config-check  ## Todo lo que ejecuta la CI

run:  ## Una busqueda real
	$(PYTHON) -m jobbot.cli run

dry-run:  ## Una busqueda que no manda nada ni gasta en LLM
	$(PYTHON) -m jobbot.cli run --dry-run --no-llm

bot:  ## Arranca el bot escuchando en Telegram
	$(PYTHON) -m jobbot.cli bot

clean:  ## Borra cachés y artefactos de build
	$(PYTHON) -c "import pathlib, shutil; \
		[shutil.rmtree(p, ignore_errors=True) for p in pathlib.Path('.').rglob('__pycache__')]; \
		[shutil.rmtree(p, ignore_errors=True) for p in ('.pytest_cache', '.ruff_cache', 'build', 'dist', 'htmlcov')]"
