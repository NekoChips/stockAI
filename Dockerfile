FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/src

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends tzdata \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml setup.py ./
COPY src ./src
RUN python -m pip install --no-cache-dir .

COPY config ./config
COPY README.md ./

ENTRYPOINT ["python", "-m", "stock_ai_agent.app"]
CMD ["monitor", "--config", "config/release.container.yaml"]
