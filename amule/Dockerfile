# Build context: the repository root.
# Debian trixie ships aMule 2.3.3 as a regular, security-maintained package (Alpine only has it
# in edge/testing), so the app uses a Debian Python image instead of BUILD_FROM.
ARG PYTHON_IMAGE=python:3.13-slim-trixie

FROM ${PYTHON_IMAGE} AS builder
COPY --from=ghcr.io/astral-sh/uv:0.13.9 /uv /bin/uv
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_NO_CACHE=1 \
    UV_PROJECT_ENVIRONMENT=/opt/venv
WORKDIR /app
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-dev --no-install-project
COPY src ./src
RUN uv sync --frozen --no-dev --no-editable

FROM ${PYTHON_IMAGE}
RUN apt-get update \
    && apt-get install -y --no-install-recommends amule-daemon \
    && apt-get upgrade -y \
    && rm -rf /var/lib/apt/lists/*
COPY --from=builder /opt/venv /opt/venv
ENV PATH=/opt/venv/bin:$PATH \
    PYTHONUNBUFFERED=1 \
    AMULE_INGRESS_ONLY=true
LABEL io.hass.type="addon" \
      io.hass.version="1.0.0" \
      org.opencontainers.image.source="https://github.com/jmanera/ha-amule" \
      org.opencontainers.image.description="aMule 2.3.3 for Home Assistant" \
      org.opencontainers.image.licenses="Apache-2.0"
WORKDIR /data
EXPOSE 8099/tcp 4662/tcp 4672/udp 4665/udp 4712/tcp
CMD ["ha-amule"]
