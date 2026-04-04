.PHONY: install test lint typecheck clean help

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-15s\033[0m %s\n", $$1, $$2}'

install: ## Install in dev mode
	pip install -e ".[dev]"

test: ## Run all tests
	pytest tests/ -v --tb=short

test-cov: ## Run tests with coverage
	pytest tests/ -v --cov=mev_kit --cov-report=term-missing

lint: ## Lint with ruff
	ruff check src/ tests/
	ruff format --check src/ tests/

format: ## Auto-format code
	ruff format src/ tests/
	ruff check --fix src/ tests/

typecheck: ## Type check with mypy
	mypy src/mev_kit/

clean: ## Remove build artifacts
	rm -rf dist/ build/ *.egg-info .pytest_cache .mypy_cache .ruff_cache
	find . -name __pycache__ -exec rm -rf {} + 2>/dev/null || true

backtest: ## Run backtest with sample data
	mev-kit backtest --config config/free.toml --data ./data/sample.parquet

paper: ## Run paper trading
	mev-kit paper --config config/free.toml

analyze: ## Analyze results
	mev-kit analyze --db ./data/results.db
