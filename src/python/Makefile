.PHONY: all check clean coverage dry-run format help install install-dev lint test
.DEFAULT_GOAL := help

# Define a helper for checking command existence
check-command = @if ! command -v $(1) > /dev/null; then \
		echo "Error: '$(1)' not found. Please run 'make install-dev' to install development tools, or ensure it is in your PATH."; \
		exit 1; \
	fi

# Show help message
help:
	@echo "Available targets:"
	@echo ""
	@echo "Development:"
	@echo "  all         - Run all tools (format and lint)"
	@echo "  check       - Run all checks without fixing (ruff, codespell, vulture)"
	@echo "  coverage    - Run unit tests with coverage report"
	@echo "  dry-run     - Run scale app in dry-run mode (use INPUT=... for file, STAGE=... for stage)"
	@echo "  format      - Format code (ruff)"
	@echo "  lint        - Lint code and fix issues (ruff, codespell)"
	@echo "  test        - Run unit tests (use TEST=... for specific test)"
	@echo ""
	@echo "Installation:"
	@echo "  install     - Install package in editable mode"
	@echo "  install-dev - Install package with dev dependencies"
	@echo ""
	@echo "Cleanup:"
	@echo "  clean       - Clean artifacts"
	@echo ""
	@echo "Help:"
	@echo "  help        - Show this help message"

# Run all tools (format, lint, test)
all: format lint test

# Run linting checks (no fix) - suitable for CI
check:
	$(call check-command,ruff)
	$(call check-command,codespell)
	$(call check-command,vulture)
	ruff check .
	ruff format --check .
	codespell --config ../../.codespellrc .
	vulture

# Clean artifacts
clean:
	rm -rf build dist *.egg-info htmlcov .coverage coverage.xml
	find . -type d -name __pycache__ -exec rm -rf {} +
	find . -type d -name .pytest_cache -exec rm -rf {} +
	find . -type d -name .mypy_cache -exec rm -rf {} +

# Run unit tests with coverage report
coverage:
	$(call check-command,pytest)
	PHENIX_LOG_FILE="" pytest --cov=phenix_apps --cov-report=term-missing --cov-report=xml:coverage.xml $(TEST)

APP ?= scale
STAGE ?= post-start
INPUT ?= phenix_apps/apps/scale/plugins/wind_turbine/tests/test_wind_turbine_input.yaml

# Run app in dry-run mode
dry-run:
	@APP=$(APP); \
	STAGE=$(STAGE); \
	INPUT=$(INPUT); \
	case "$$STAGE" in \
		configure|pre-start|post-start|running|cleanup) ;; \
		*) echo "Error: Invalid stage '$$STAGE'. Valid stages are: configure, pre-start, post-start, running, cleanup"; exit 1 ;; \
	esac; \
	if [ ! -f "$$INPUT" ]; then \
		echo "Error: Input file '$$INPUT' not found."; \
		exit 1; \
	fi; \
	PHENIX_LOG_FILE="" PHENIX_LOG_LEVEL=debug phenix-app-$(APP) $$STAGE --dry-run < $$INPUT

# Format code (ruff)
format:
	$(call check-command,ruff)
	ruff check --fix .
	ruff format .

# Install package in editable mode
install:
	$(call check-command,pip)
	PIP_BREAK_SYSTEM_PACKAGES=1 pip install -e "."

# Install package with dev dependencies
install-dev:
	$(call check-command,pip)
	PIP_BREAK_SYSTEM_PACKAGES=1 pip install -e ".[dev]"

# Lint code (ruff, codespell, vulture)
lint:
	$(call check-command,ruff)
	$(call check-command,codespell)
	ruff check . --fix
	codespell --config ../../.codespellrc . -w

# Run unit tests
test:
	$(call check-command,pytest)
	PHENIX_LOG_FILE="" pytest $(TEST)
