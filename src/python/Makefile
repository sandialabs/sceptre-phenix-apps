.PHONY: all check clean coverage dry-run format help install install-dev lint test

# Show help message
help:
	@echo "Available targets:"
	@echo "  all      - Run all tools (format and lint)"
	@echo "  clean    - Clean build artifacts"
	@echo "  format   - Format code (ruff)"
	@echo "  check    - Run linting checks without fixing (CI)"
	@echo "  dry-run  - Run scale app in dry-run mode (use INPUT=... for file, STAGE=... for stage)"
	@echo "  coverage - Run unit tests with coverage report"
	@echo "  help     - Show this help message"
	@echo "  install  - Install package in editable mode"
	@echo "  install-dev - Install package with dev dependencies"
	@echo "  lint     - Lint code (ruff, codespell, vulture)"
	@echo "  test     - Run unit tests (use TEST=... for specific test)"

# Run all tools (format and lint)
all: format lint

# Run linting checks (no fix) - suitable for CI
check:
	ruff check .
	ruff format --check .
	ruff check --select I .

# Clean build artifacts
clean:
	rm -rf build dist *.egg-info htmlcov .coverage
	find . -type d -name __pycache__ -exec rm -rf {} +
	find . -type d -name .pytest_cache -exec rm -rf {} +
	find . -type d -name .mypy_cache -exec rm -rf {} +

# Run unit tests with coverage report
coverage:
	PHENIX_LOG_FILE="" pytest --cov=phenix_apps --cov-report=term-missing $(TEST)

# Run scale app in dry-run mode
dry-run:
	@INPUT=$(or $(INPUT),phenix_apps/apps/scale/plugins/wind_turbine/tests/test_wind_turbine_input.yaml); \
	STAGE=$(or $(STAGE),post-start); \
	case "$$STAGE" in \
		configure|pre-start|post-start|running|cleanup) ;; \
		*) echo "Error: Invalid stage '$$STAGE'. Valid stages are: configure, pre-start, post-start, running, cleanup"; exit 1 ;; \
	esac; \
	if [ ! -f "$$INPUT" ]; then \
		echo "Error: Input file '$$INPUT' not found."; \
		exit 1; \
	fi; \
	PHENIX_LOG_FILE="" PHENIX_LOG_LEVEL=debug phenix-app-scale $$STAGE --dry-run < $$INPUT

# Format code (ruff)
format:
	ruff check --select I --fix .
	ruff format .

# Install package in editable mode
install:
	pip install -e "."

# Install package with dev dependencies
install-dev:
	pip install -e ".[dev]"

# Lint code (ruff, codespell, vulture)
lint:
	ruff check . --fix
	codespell
	vulture .

# Run unit tests
test:
	PHENIX_LOG_FILE="" pytest $(TEST)
