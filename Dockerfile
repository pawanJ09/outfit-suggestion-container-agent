# AgentCore Runtime requires ARM64. This image is always built with
# `docker buildx build --platform linux/arm64`, cross-compiled on GitHub
# Actions' x86_64 runners via QEMU (see .github/workflows/deploy.yml) --
# the --platform flag at build time is what actually matters; this FROM
# line just pins a consistent base.
FROM --platform=linux/arm64 python:3.14-slim

WORKDIR /app

# Runtime dependencies only -- requirements-dev.txt (ruff/pytest) never
# ships in the image.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# src/ and config/ as siblings, matching the repo layout exactly, so
# agent.py's local-file fallback for instructions.txt resolves correctly
# with no path translation needed between repo and container.
COPY src/ src/
COPY config/ config/

# AgentCore Runtime's mandatory HTTP contract: the container must listen
# on 0.0.0.0:8080 and expose POST /invocations + GET /ping. Both are
# handled automatically by BedrockAgentCoreApp inside agent.py -- nothing
# else to configure here.
EXPOSE 8080

CMD ["python", "src/agent.py"]
