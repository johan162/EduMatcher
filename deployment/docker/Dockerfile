# EduMatcher container image — the whole exchange in a single container.
#
# Stage 1 builds the runtime virtualenv; stage 2 keeps only that venv plus the
# handful of OS tools pm-opctl-cli needs, so pip caches and build leftovers
# never reach the final image.
#
# The image deliberately mirrors the Multipass runtime VM (deployment/vm/): a dedicated
# venv under /opt/edumatcher/.venv with every pm-* command on PATH.

ARG PYTHON_VERSION=3.13

# ---------------------------------------------------------------------------
# Stage 1 — build the runtime venv
# ---------------------------------------------------------------------------
FROM python:${PYTHON_VERSION}-slim-bookworm AS builder

ARG EDUMATCHER_VERSION=""

# Set to a corporate PyPI proxy (e.g. Artifactory) when building behind a
# firewall; left empty, pip falls back to its default index (PyPI).
ARG PIP_INDEX_URL

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

# .wheel/ contains a locally built wheel when `make build DEV=1` placed one
# there, and only .keep otherwise. Its presence selects the install source.
COPY .wheel/ /tmp/wheel/

RUN python -m venv /opt/edumatcher/.venv && \
    PIP_ARGS=""; \
    if [ -n "${PIP_INDEX_URL}" ]; then PIP_ARGS="--index-url ${PIP_INDEX_URL}"; fi; \
    if ls /tmp/wheel/*.whl >/dev/null 2>&1; then \
        echo "Installing local wheel: $(ls /tmp/wheel/*.whl)" && \
        /opt/edumatcher/.venv/bin/pip install ${PIP_ARGS} /tmp/wheel/*.whl; \
    elif [ -n "${EDUMATCHER_VERSION}" ]; then \
        /opt/edumatcher/.venv/bin/pip install ${PIP_ARGS} "edumatcher==${EDUMATCHER_VERSION}"; \
    else \
        /opt/edumatcher/.venv/bin/pip install ${PIP_ARGS} edumatcher; \
    fi

# ---------------------------------------------------------------------------
# Stage 2 — runtime
# ---------------------------------------------------------------------------
FROM python:${PYTHON_VERSION}-slim-bookworm

ARG WITH_SSH=1

# procps  — pm-opctl-cli uses pgrep/ps to adopt processes and report uptime/RSS
# tini    — PID 1 that reaps the processes pm-opctl-cli detaches
# tzdata  — the scheduler and market calendars need a real zoneinfo database
RUN apt-get -o Acquire::Check-Valid-Until=false -o Acquire::Check-Date=false update && \
    apt-get install -y --no-install-recommends \
        ca-certificates \
        curl \
        procps \
        tini \
        tzdata && \
    if [ "${WITH_SSH}" = "1" ]; then \
        apt-get install -y --no-install-recommends openssh-server; \
    fi && \
    rm -rf /var/lib/apt/lists/*

COPY --from=builder /opt/edumatcher/.venv /opt/edumatcher/.venv

ENV PATH="/opt/edumatcher/.venv/bin:${PATH}" \
    EDUMATCHER_DATA_DIR=/data \
    PYTHONUNBUFFERED=1

# An ssh login does not inherit image ENV, so the same two settings are also
# written where every interactive shell picks them up.
RUN printf '%s\n' \
        'export PATH=/opt/edumatcher/.venv/bin:$PATH' \
        'export EDUMATCHER_DATA_DIR=/data' \
        > /etc/profile.d/edumatcher.sh && \
    cat /etc/profile.d/edumatcher.sh >> /root/.bashrc

COPY entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod +x /usr/local/bin/entrypoint.sh

# Documentation only; the compose files decide what is actually published.
EXPOSE 5555 5556 5557 5558 5559 5560 5565 5570 5580 5590 5600 5601 5602 8080 8081 22

# Deliberately the engine's order-intake socket rather than
# `pm-opctl-cli health -q`: that command reports FAIL on the stock 'default'
# profile because its index-srv entry probes 127.0.0.1:5610 while pm-index
# binds 5558/5559. `make health` still shows the full per-process table.
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD python -c "import socket; socket.create_connection(('127.0.0.1', 5555), 3).close()" || exit 1

ENTRYPOINT ["/usr/bin/tini", "--", "/usr/local/bin/entrypoint.sh"]
