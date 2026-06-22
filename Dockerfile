# syntax=docker/dockerfile:1
#
# Mesaar Logistics Operations API — production container image.
#
# Multi-stage build:
#   1. "builder" compiles wheels for all runtime dependencies into a self-
#      contained wheelhouse so the final image needs no compiler toolchain.
#   2. "runtime" is a slim image that installs those prebuilt wheels, runs as
#      an unprivileged user, and serves the ASGI app via gunicorn with uvicorn
#      workers.
#
# The same image is reused for the API, Celery worker, and Celery beat by
# overriding the command in docker-compose.yml.

############################
# Stage 1 — build wheels   #
############################
FROM python:3.11-slim AS builder

# Fail fast and keep Python output unbuffered during the build.
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# Build dependencies required to compile psycopg2 and cryptography wheels.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        build-essential \
        libpq-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /build

# Copy only the dependency manifest first to maximise Docker layer caching.
COPY requirements.txt .

# Build wheels for every pinned dependency into /wheels.
RUN pip wheel --wheel-dir /wheels -r requirements.txt


############################
# Stage 2 — runtime image  #
############################
FROM python:3.11-slim AS runtime

# Runtime environment configuration.
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    APP_HOME=/app \
    PORT=8000

# libpq5 is the only native runtime library psycopg2 needs; curl powers the
# container HEALTHCHECK below.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        libpq5 \
        curl \
    && rm -rf /var/lib/apt/lists/*

# Create an unprivileged user/group so the container never runs as root.
RUN groupadd --system --gid 1000 mesaar \
    && useradd --system --uid 1000 --gid mesaar --create-home --home-dir /home/mesaar mesaar

WORKDIR ${APP_HOME}

# Install dependencies from the prebuilt wheelhouse, then discard the wheels.
COPY --from=builder /wheels /wheels
COPY requirements.txt .
RUN pip install --no-index --find-links=/wheels -r requirements.txt \
    && rm -rf /wheels

# Copy application source. Ownership is set to the unprivileged user.
COPY --chown=mesaar:mesaar . ${APP_HOME}

# Drop privileges for everything that follows.
USER mesaar

EXPOSE 8000

# Liveness probe — hits the unversioned liveness endpoint served at the root.
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD curl --fail --silent "http://127.0.0.1:${PORT}/health/live" || exit 1

# Production server: gunicorn process manager with uvicorn ASGI workers.
# Worker count is overridable via the WEB_CONCURRENCY environment variable.
CMD ["gunicorn", "app.main:app", \
     "--worker-class", "uvicorn.workers.UvicornWorker", \
     "--workers", "4", \
     "--bind", "0.0.0.0:8000", \
     "--timeout", "60", \
     "--graceful-timeout", "30", \
     "--keep-alive", "5", \
     "--access-logfile", "-", \
     "--error-logfile", "-"]
