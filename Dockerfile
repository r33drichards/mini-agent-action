FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# Install curl and build tooling for native extensions
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    ca-certificates \
    xz-utils \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Install uv (non-interactive)
RUN curl -LsSf https://astral.sh/uv/install.sh | sh
ENV PATH="/root/.local/bin:${PATH}"

WORKDIR /app

# Copy only the files needed to build the wheel
COPY pyproject.toml README.md ./
COPY main.py ./

# Build the wheel and install it with uv; wildcard ensures any version is accepted
RUN uv build
RUN uv pip install --system dist/mini_agent_action-*.whl

# Quick smoke test to ensure the CLI is available
RUN mini-agent-action -h | head -n 1

ENTRYPOINT ["mini-agent-action"]

