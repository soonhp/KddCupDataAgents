FROM python:3.11-slim

ARG STARTER_KIT_REPO=https://github.com/HKUSTDial/kddcup2026-data-agents-starter-kit
ARG STARTER_KIT_REF=c6992b07bcd320b7904505c92c6ba7f7c77e4857

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends git ca-certificates \
    && rm -rf /var/lib/apt/lists/*

RUN git clone --filter=blob:none "${STARTER_KIT_REPO}" /opt/kddcup-starter-kit \
    && cd /opt/kddcup-starter-kit \
    && git fetch --depth 1 origin "${STARTER_KIT_REF}" \
    && git checkout --detach FETCH_HEAD \
    && pip install --no-cache-dir /opt/kddcup-starter-kit

WORKDIR /app
COPY runner /app/runner
COPY scripts /app/scripts
COPY docker/entrypoint.sh /app/entrypoint.sh

RUN chmod +x /app/entrypoint.sh

ENTRYPOINT ["/app/entrypoint.sh"]
