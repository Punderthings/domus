# syntax=docker/dockerfile:1
#
# The Domus image: the backend, its CLI, and the built front end in one container.
# Build from the repository root:
#
#   docker build -f deploy/Dockerfile -t domus:local .
#
# Data (SQLite database, files, backups) lives in /data; mount a volume there.

ARG PYTHON_IMAGE=python:3.14-slim
ARG NODE_IMAGE=node:22-slim

# --- Front end: npm ci, then vite build into src/domus/static -----------------
FROM ${NODE_IMAGE} AS frontend
WORKDIR /src/src/frontend
COPY src/frontend/package.json src/frontend/package-lock.json ./
# --ignore-scripts: no install scripts from any package run during the build.
RUN npm ci --ignore-scripts
COPY src/frontend/ ./
RUN npm run build

# --- Python: install the locked runtime dependencies and the package ---------
FROM ${PYTHON_IMAGE} AS build
# uv comes from PyPI at a pinned version, like the rest of the toolchain.
ARG UV_VERSION=0.11.32
RUN pip install --no-cache-dir --root-user-action=ignore "uv==${UV_VERSION}"
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/opt/domus/venv
WORKDIR /src
# Dependencies first, so editing the code doesn't reinstall them.
COPY pyproject.toml uv.lock README.md LICENSE NOTICE ./
RUN uv sync --locked --no-dev --no-install-project
COPY src/domus ./src/domus
COPY --from=frontend /src/src/domus/static ./src/domus/static
# --no-editable installs a built wheel, so /src isn't needed at run time.
RUN uv sync --locked --no-dev --no-editable

# --- Runtime -----------------------------------------------------------------
FROM ${PYTHON_IMAGE}
ARG DOMUS_VERSION=dev
LABEL org.opencontainers.image.title="Domus" \
      org.opencontainers.image.description="Home inventory, maintenance, and Home Assistant helper" \
      org.opencontainers.image.source="https://github.com/punderthings/domus" \
      org.opencontainers.image.licenses="Apache-2.0" \
      org.opencontainers.image.version="${DOMUS_VERSION}"

# A fixed, unprivileged uid so volume ownership stays the same across rebuilds.
RUN groupadd --gid 10001 domus \
    && useradd --uid 10001 --gid domus --home-dir /data --no-create-home \
       --shell /usr/sbin/nologin domus \
    && mkdir /data \
    && chown domus:domus /data

COPY --from=build /opt/domus/venv /opt/domus/venv
# The sample dataset, for `domus restore /opt/domus/examples/sample-home --merge`.
COPY examples /opt/domus/examples

ENV PATH="/opt/domus/venv/bin:${PATH}" \
    DOMUS_DATA_DIR=/data \
    DOMUS_SAMPLE_DATA_DIR=/opt/domus/examples/sample-home \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

USER domus
WORKDIR /data
VOLUME ["/data"]
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/v1/health', timeout=4)"]

# Listens on all interfaces inside the container; compose.yaml publishes it on
# 127.0.0.1 only.
CMD ["domus", "serve", "--host", "0.0.0.0", "--port", "8000"]
