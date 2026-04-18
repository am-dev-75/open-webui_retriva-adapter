FROM python:3.12-slim AS builder

WORKDIR /build
COPY pyproject.toml ./
RUN pip install --no-cache-dir uv \
    && uv pip install --system --no-cache ".[dev]"

COPY src/ src/

# -------------------------------------------------------------------
FROM python:3.12-slim AS runtime

RUN groupadd --gid 1000 adapter \
    && useradd --uid 1000 --gid adapter --create-home adapter

WORKDIR /app
COPY --from=builder /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin
COPY src/ src/

RUN mkdir -p /data && chown adapter:adapter /data
VOLUME ["/data"]

USER adapter

ENV PYTHONPATH=/app/src \
    DB_PATH=/data/adapter.db \
    ADAPTER_PORT=8500

EXPOSE 8500

HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8500/healthz')" || exit 1

CMD ["python", "-m", "adapter"]
