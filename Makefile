# NEXUS V12.4 COGNITIVE BOOST - Development Commands
#
# Usage:
#   make install     - Install all dependencies
#   make test        - Run full test suite
#   make lint        - Run linter (ruff)
#   make type-check  - Run type checker (mypy)
#   make run         - Launch interactive REPL
#   make headless    - Run in headless mode
#   make clean       - Remove cached files
#   make ci          - Run full CI pipeline locally

.PHONY: install install-dev install-rust test test-fast test-cov lint type-check \
        format run headless verify clean ci security-scan kernel-check

# =============================================================================
# Configuration
# =============================================================================

PYTHON ?= python
PYTEST_ARGS ?= -q --tb=short
RUFF_ARGS ?= check core/ tests/ nexus7.py

# =============================================================================
# Installation
# =============================================================================

install:  ## Install production dependencies
	$(PYTHON) -m pip install --upgrade pip
	$(PYTHON) -m pip install -r requirements.txt

install-dev: install  ## Install dev + test dependencies
	$(PYTHON) -m pip install ruff mypy pytest-cov pytest-timeout bandit

install-rust:  ## Install Rust toolchain for native extensions
	$(PYTHON) -m pip install maturin
	cd rust/nexus_core && maturin develop --release

# =============================================================================
# Testing
# =============================================================================

test:  ## Run full test suite (see CI evidence ledger for current counts)
	@echo "⚠️  Warning: Full test suite uses significant memory (2-3GB)"
	@echo "   Consider 'make test-fast' or 'make test-unit' for development"
	$(PYTHON) -m pytest tests/ $(PYTEST_ARGS) --ignore=tests/benchmark_professional.py

test-fast:  ## Run tests excluding slow E2E tests (recommended for development)
	$(PYTHON) -m pytest tests/ $(PYTEST_ARGS) \
		--ignore=tests/benchmark_professional.py \
		--ignore=tests/test_headless_e2e.py \
		-m "not slow and not integration" \
		-x

test-unit:  ## Run unit tests by domain (memory-safe, sequential)
	@echo "Running tests by domain to limit memory usage..."
	$(PYTHON) -m pytest tests/fsm/ tests/memory/ tests/utils/ -q --tb=short
	$(PYTHON) -m pytest tests/drivers/ tests/execution/ -q --tb=short
	$(PYTHON) -m pytest tests/swarm/ tests/hive_mind/ -q --tb=short

test-cov:  ## Run tests with coverage report
	$(PYTHON) -m pytest tests/ \
		--cov=core --cov-report=term-missing:skip-covered \
		--cov-report=html --cov-fail-under=40 \
		--ignore=tests/benchmark_professional.py

test-v11:  ## Run V11 CEREBRO API tests only
	$(PYTHON) -m pytest tests/v11/ -v --tb=short

# =============================================================================
# Code Quality
# =============================================================================

lint:  ## Run ruff linter
	$(PYTHON) -m ruff $(RUFF_ARGS)

format:  ## Auto-format code with ruff
	$(PYTHON) -m ruff format core/ tests/ nexus7.py

type-check:  ## Run mypy type checker
	$(PYTHON) -m mypy core/memory/types.py core/native/ core/security/password.py \
		--ignore-missing-imports

security-scan:  ## Run bandit security scanner
	$(PYTHON) -m bandit -r core/ -ll

kernel-check:  ## Verify KERNEL.py integrity
	$(PYTHON) -c "\
	import hashlib; \
	content = open('KERNEL.py', 'rb').read(); \
	actual = hashlib.sha256(content).hexdigest(); \
	expected = open('KERNEL_HASH.txt').read().strip().split(':')[-1]; \
	print(f'OK: {actual[:16]}...' if actual == expected else f'FAIL: {actual} != {expected}'); \
	exit(0 if actual == expected else 1)"

# =============================================================================
# Running
# =============================================================================

run:  ## Launch interactive NEXUS REPL
	$(PYTHON) nexus7.py

headless:  ## Run in headless mode (boot validation)
	$(PYTHON) nexus7.py --headless

verify:  ## Verify NEXUS installation
	$(PYTHON) nexus7.py --verify

# =============================================================================
# Maintenance
# =============================================================================

clean:  ## Remove cached files and build artifacts
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete 2>/dev/null || true
	rm -rf .pytest_cache .mypy_cache .ruff_cache htmlcov
	rm -rf build dist *.egg-info
	rm -f coverage.xml .coverage

# =============================================================================
# CI Pipeline (local execution)
# =============================================================================

ci: lint kernel-check test  ## Run full CI pipeline locally
	@echo ""
	@echo "=== CI Pipeline PASSED ==="
