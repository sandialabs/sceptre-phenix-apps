.PHONY: help install format lint test all

# Show help message
help:
	@echo "Available targets:"
	@echo "  help     - Show this help message"
	@echo "  install  - Install golangci-lint"
	@echo "  format   - Format code (golangci-lint)"
	@echo "  lint     - Lint code (golangci-lint, codespell)"
	@echo "  test     - Run unit tests"
	@echo "  all      - Run all tools (format, lint, and test)"

install:
	curl -sSfL https://raw.githubusercontent.com/golangci/golangci-lint/HEAD/install.sh | sh -s -- -b $(go env GOPATH)/bin v2.7.2
	sudo apt-get install -y codespell

format:
	golangci-lint fmt ./...

lint:
	golangci-lint run ./...
	codespell --config ../../.codespellrc .

test:
	go test -v ./...

all: format lint test