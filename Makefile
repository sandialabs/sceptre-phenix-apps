.PHONY: help install format lint test all

help:
	@echo "Available targets:"
	@echo "  help     - Show this help message"
	@echo "  install  - Install tools"
	@echo "  format   - Format code (golangci-lint, ruff)"
	@echo "  lint     - Lint code (golangci-lint, ruff, codespell, vulture)"
	@echo "  test     - Run unit tests"
	@echo "  all      - Run all tools (format, lint, and test)"

install format lint test all:
	@make -C src/go $@
	@make -C src/python $@