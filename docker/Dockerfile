FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends git ca-certificates \
    && rm -rf /var/lib/apt/lists/*

RUN git clone --depth 1 https://github.com/HKUSTDial/kddcup2026-data-agents-starter-kit /opt/kddcup-starter-kit \
    && pip install --no-cache-dir /opt/kddcup-starter-kit

WORKDIR /app
COPY runner /app/runner
COPY docker/entrypoint.sh /app/entrypoint.sh

RUN chmod +x /app/entrypoint.sh

ENTRYPOINT ["/app/entrypoint.sh"]
