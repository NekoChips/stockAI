FROM python:3.12-slim AS builder

ENV PIP_DEFAULT_TIMEOUT=120 \
    PIP_RETRIES=5

WORKDIR /build

RUN python -m venv /opt/venv

ENV PATH="/opt/venv/bin:$PATH"

ARG PIP_INDEX_URL
COPY pyproject.toml README.md ./
COPY src ./src
RUN if [ -n "$PIP_INDEX_URL" ]; then \
        python -m pip install --no-cache-dir --index-url "$PIP_INDEX_URL" .; \
    else \
        python -m pip install --no-cache-dir .; \
    fi

FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/src \
    PATH="/opt/venv/bin:$PATH"

RUN apt-get update \
    && apt-get install -y --no-install-recommends tzdata \
    && rm -rf /var/lib/apt/lists/*

RUN useradd --create-home --shell /usr/sbin/nologin stockai

COPY --from=builder /opt/venv /opt/venv

WORKDIR /app

COPY config ./config
COPY README.md ./

USER stockai

ENTRYPOINT ["python", "-m", "stock_ai_agent.app"]
CMD ["monitor", "--config", "config/release.container.yaml"]
