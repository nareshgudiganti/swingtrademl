# Multi-stage: build wheels once, then ship a slim runtime image.
# The heavy scientific stack (numpy, scipy, scikit-learn, lightgbm) needs build
# tooling that has no business being in the final image.

FROM python:3.12-slim AS builder

ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        libpq-dev \
        # lightgbm links against libgomp at build and run time
        libgomp1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /build
COPY pyproject.toml ./
COPY src ./src

RUN pip install --upgrade pip setuptools wheel \
    && pip wheel --wheel-dir /wheels .


FROM python:3.12-slim AS runtime

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

RUN apt-get update && apt-get install -y --no-install-recommends \
        libpq5 \
        libgomp1 \
        curl \
    && rm -rf /var/lib/apt/lists/*

# Non-root: a container that can write to its own filesystem is a container an
# exploited dependency can persist in.
RUN useradd --create-home --uid 1000 appuser

WORKDIR /app

COPY --from=builder /wheels /wheels
RUN pip install --no-index --find-links=/wheels swing-trade-ml && rm -rf /wheels

COPY alembic.ini ./
COPY alembic ./alembic
COPY src ./src

# Model artifacts are written at runtime and must survive as a mounted volume;
# the directory has to exist and be writable by appuser first.
RUN mkdir -p /app/data/models && chown -R appuser:appuser /app

USER appuser

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=40s --retries=3 \
    CMD curl -fsS http://localhost:8000/api/v1/health || exit 1

CMD ["uvicorn", "swing_trade_ml.main:app", "--host", "0.0.0.0", "--port", "8000"]
