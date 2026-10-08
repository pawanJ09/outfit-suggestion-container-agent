.PHONY: check lint format test build run clean install help

PYTHON        := python3
SRC_DIR       := src
TEST_DIR      := tests
IMAGE_NAME    := outfit-suggestion-container-agent
IMAGE_TAG     := local
COV_MIN       := 90

help:
	@echo "Targets:"
	@echo "  make install  - install runtime + dev dependencies"
	@echo "  make check    - format, lint, and test (local dev flow)"
	@echo "  make build    - build the ARM64 container image locally"
	@echo "  make run      - run the built image locally on port 8080"
	@echo "  make clean    - remove caches"

install:
	$(PYTHON) -m pip install -r requirements.txt
	$(PYTHON) -m pip install -r requirements-dev.txt

## ---- Flow 1: format, lint, test ----
check: format lint test

format:
	ruff format $(SRC_DIR) $(TEST_DIR)

lint:
	ruff check $(SRC_DIR) $(TEST_DIR)

test:
	pytest --cov=$(SRC_DIR) --cov-report=term-missing --cov-fail-under=$(COV_MIN)

## ---- Flow 2: build and run the container locally ----
# Requires Docker with buildx (for ARM64 cross-build on non-ARM hosts).
build:
	docker buildx build --platform linux/arm64 -t $(IMAGE_NAME):$(IMAGE_TAG) --load .

run:
	docker run --platform linux/arm64 -p 8080:8080 \
		-e AWS_ACCESS_KEY_ID="$$AWS_ACCESS_KEY_ID" \
		-e AWS_SECRET_ACCESS_KEY="$$AWS_SECRET_ACCESS_KEY" \
		-e AWS_SESSION_TOKEN="$$AWS_SESSION_TOKEN" \
		-e AWS_REGION="$${AWS_REGION:-us-east-1}" \
		$(IMAGE_NAME):$(IMAGE_TAG)

clean:
	rm -rf .pytest_cache .ruff_cache .coverage htmlcov
	find . -type d -name "__pycache__" -exec rm -rf {} +
