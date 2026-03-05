.PHONY: all check clean coverage format help install install-dev lint lint-clean test
.pythopnDEFAULT_GOAL := help

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
	@echo "  all         - Run all tools (format, lint, and test)"
	@echo "  check       - Run linters without fixing (for CI)"
	@echo "  coverage       - Run unit tests with coverage"
	@echo "  format      - Format code (golangci-lint)"
	@echo "  lint        - Lint code and fix issues (golangci-lint)"
	@echo "  lint-clean  - Clean lint cache (golangci-lint)"
	@echo "  test        - Run unit tests"
	@echo ""
	@echo "Installation:"
	@echo "  install     - Install Go module dependencies"
	@echo "  install-dev - Install development tools (golangci-lint)"
	@echo ""
	@echo "Cleanup:"
	@echo "  clean       - Clean artifacts"
	@echo ""
	@echo "Help:"
	@echo "  help        - Show this help message"

GOBIN         ?= $(shell go env GOPATH)/bin
# Use golangci-lint from PATH if available (e.g. CI), otherwise use local install
GOLANGCI_LINT ?= $(shell command -v golangci-lint 2> /dev/null || echo $(GOBIN)/golangci-lint)

all: format lint test

check:
	$(call check-command,$(GOLANGCI_LINT))
	$(GOLANGCI_LINT) run -c .golangci.yml

install:
	$(call check-command,go)
	go mod tidy

install-dev:
	$(call check-command,curl)
	curl -sSfL https://raw.githubusercontent.com/golangci/golangci-lint/HEAD/install.sh | sh -s -- -b $(GOBIN) v2.10.1

format:
	$(call check-command,$(GOLANGCI_LINT))
	$(GOLANGCI_LINT) fmt -c .golangci.yml

lint:
	$(call check-command,$(GOLANGCI_LINT))
	$(GOLANGCI_LINT) run -c .golangci.yml --fix

lint-clean:
	$(call check-command,$(GOLANGCI_LINT))
	$(GOLANGCI_LINT) cache clean

test:
	$(call check-command,go)
	go test -v ./...

coverage:
	$(call check-command,go)
	go test -v -race -coverprofile=coverage.out ./...
	go tool cover -func=coverage.out

clean: lint-clean
	$(call check-command,go)
	go clean
