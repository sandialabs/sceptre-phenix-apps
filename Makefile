.PHONY: all check clean format help install install-dev lint test
.PHONY: go-check go-clean go-coverage go-format go-install-dev go-lint go-test
.PHONY: python-check python-clean python-coverage python-format python-install-dev python-lint python-test
.DEFAULT_GOAL := help

help:
	@echo "Available targets:"
	@echo ""
	@echo "Development:"
	@echo "  all         - Run all tools (format, lint, test)"
	@echo "  check       - Run linters without fixing (for CI)"
	@echo "  format      - Format code (golangci-lint, ruff)"
	@echo "  lint        - Lint code and fix issues (golangci-lint, ruff, etc.)"
	@echo "  test        - Run unit tests"
	@echo ""
	@echo "Installation:"
	@echo "  install     - Install runtime dependencies"
	@echo "  install-dev - Install development dependencies and tools"
	@echo ""
	@echo "Cleanup:"
	@echo "  clean       - Clean build artifacts"
	@echo ""
	@echo "Help:"
	@echo "  help        - Show this help message"

all: format lint test

check: python-check go-check
test: python-test go-test
lint: python-lint go-lint
format: python-format go-format
install-dev: python-install-dev go-install-dev
clean: python-clean go-clean
coverage: python-coverage go-coverage

## ---------------------------------- Python ----------------------------------

python-check:
	@$(MAKE) -C src/python check

python-install:
	@$(MAKE) -C src/python install

python-install-dev:
	@$(MAKE) -C src/python install-dev

python-format:
	@$(MAKE) -C src/python format

python-lint:
	@$(MAKE) -C src/python lint

python-test:
	@$(MAKE) -C src/python test

python-clean:
	@$(MAKE) -C src/python clean

python-coverage:
	@$(MAKE) -C src/python coverage

## ---------------------------------- Go ----------------------------------

go-check:
	@$(MAKE) -C src/go check

go-install:
	@$(MAKE) -C src/go install

go-install-dev:
	@$(MAKE) -C src/go install-dev

go-format:
	@$(MAKE) -C src/go format

go-lint:
	@$(MAKE) -C src/go lint

go-test:
	@$(MAKE) -C src/go test

go-clean:
	@$(MAKE) -C src/go clean

go-coverage:
	@$(MAKE) -C src/go coverage

