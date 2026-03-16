# NEXUS V12.4 COGNITIVE BOOST - Multi-Stage Docker Build
#
# Stages:
#   1. rust-builder: Compile Rust native extensions (optional)
#   2. python-deps: Install Python dependencies in virtualenv
#   3. runtime: Minimal production image
#
# Usage:
#   docker build -t nexus:12.4 .
#   docker build --target runtime --build-arg RUST_EXTENSIONS=false -t nexus:12.4-slim .
#
# Environment Variables (runtime):
#   ANTHROPIC_API_KEY    - Anthropic API key for Claude SDK driver
#   GOOGLE_API_KEY       - Google API key for Gemini SDK driver
#   REDIS_URL            - Redis connection URL (default: redis://redis:6379)
#   NEXUS_DRIVER_MODE    - Driver mode: auto, sdk, cli (default: auto)
#   LOG_LEVEL            - Logging level (default: INFO)

# =============================================================================
# Stage 1: Rust Native Extensions (optional)
# =============================================================================
FROM python:3.13-slim AS rust-builder

ARG RUST_EXTENSIONS=false

RUN if [ "$RUST_EXTENSIONS" = "true" ]; then \
        apt-get update && apt-get install -y --no-install-recommends \
            curl build-essential && \
        curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y && \
        . $HOME/.cargo/env && \
        pip install --no-cache-dir maturin; \
    fi

WORKDIR /build
COPY rust/ rust/

RUN if [ "$RUST_EXTENSIONS" = "true" ] && [ -d "rust/nexus_core" ]; then \
        . $HOME/.cargo/env && \
        cd rust/nexus_core && \
        maturin build --release --out /build/wheels; \
    else \
        mkdir -p /build/wheels; \
    fi

# =============================================================================
# Stage 2: Python Dependencies
# =============================================================================
FROM python:3.13-slim AS python-deps

# Install system dependencies for sentence-transformers, lancedb, etc.
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        git \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Create virtualenv
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Install Python deps (cached layer - only re-runs if requirements change)
COPY pyproject.toml requirements.txt ./
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Install SDK drivers (not in requirements.txt, part of optional extras)
RUN pip install --no-cache-dir anthropic>=0.70.0 google-genai>=1.0.0

# Install Rust wheels if any
COPY --from=rust-builder /build/wheels/ /tmp/wheels/
RUN if ls /tmp/wheels/*.whl 1>/dev/null 2>&1; then \
        pip install --no-cache-dir /tmp/wheels/*.whl; \
    fi && \
    rm -rf /tmp/wheels

# =============================================================================
# Stage 3: Runtime
# =============================================================================
FROM python:3.13-slim AS runtime

# Labels
LABEL maintainer="Yann Abadie"
LABEL version="12.4.0"
LABEL description="NEXUS V12.4 COGNITIVE BOOST - Multi-Agent Orchestrator"

# Install minimal runtime dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
        tini \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd -r nexus && useradd -r -g nexus -m nexus

# Copy virtualenv from builder
COPY --from=python-deps /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

# Application code
WORKDIR /app
COPY core/ core/
COPY prompts/ prompts/
COPY nexus7.py KERNEL.py KERNEL_HASH.txt MISSION.md ./
COPY pyproject.toml requirements.txt ./

# Create workspace directory (volume mount point)
RUN mkdir -p workspace/.nexus workspace/logs workspace/agents && \
    chown -R nexus:nexus /app

# Default environment
ENV NEXUS_DRIVER_MODE=auto
ENV REDIS_URL=redis://redis:6379
ENV LOG_LEVEL=INFO
ENV WORKSPACE_PATH=/app/workspace
ENV NEXUS_FF_HEADLESS_MODE=true

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=10s --retries=3 \
    CMD python -c "from core.config import load_config; c = load_config(); print('OK')"

# Run as non-root
USER nexus

# Volumes
VOLUME ["/app/workspace"]

# Default entrypoint: headless mode
ENTRYPOINT ["tini", "--"]
CMD ["python", "nexus7.py", "--headless"]
