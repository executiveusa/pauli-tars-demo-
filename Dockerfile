# BARS sovereign runtime — stdlib-only Python server, no pip installs required.
# digest-pinned official base (multi-arch index incl. linux/amd64; verified
# against registry-1.docker.io and the VPS daemon on 2026-09-10)
FROM python:3.14-slim@sha256:cad9a2c871761c413caa6fdd6441c783451e740a48aaeba60ae62a8b53525ef6

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    BARS_DATA_DIR=/data \
    BARS_BIND=0.0.0.0 \
    BARS_PORT=4321 \
    BARS_NO_BROWSER=1 \
    BARS_DISABLE_HANDS=1 \
    BARS_INTERNAL_WORKER=1

WORKDIR /app
COPY . /app

# runtime identity comes from image provenance, not a runtime env echo
ARG BARS_SHA=unknown
RUN echo "$BARS_SHA" > /app/.bars_sha

RUN useradd --system --uid 10001 --home-dir /data bars \
    && mkdir -p /data \
    && chown -R bars:bars /data

USER bars
EXPOSE 4321
VOLUME ["/data"]

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
  CMD python -c "import urllib.request,sys;sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:4321/health',timeout=4).status==200 else 1)"

CMD ["python", "server.py"]
