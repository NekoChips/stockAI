FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/src \
    PIP_DEFAULT_TIMEOUT=120 \
    PIP_RETRIES=5

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends tzdata \
    && rm -rf /var/lib/apt/lists/*

ARG PIP_INDEX_URL
RUN if [ -n "$PIP_INDEX_URL" ]; then \
        python -m pip install --no-cache-dir --index-url "$PIP_INDEX_URL" "akshare>=1.15" "PyMySQL>=1.1"; \
    else \
        python -m pip install --no-cache-dir "akshare>=1.15" "PyMySQL>=1.1"; \
    fi

COPY src ./src

COPY config ./config
COPY README.md ./

ENTRYPOINT ["python", "-m", "stock_ai_agent.app"]
CMD ["monitor", "--config", "config/release.container.yaml"]
