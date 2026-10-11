# wapt-webconsole backend: FastAPI app + waptpython (WAPT Linux agent) for signatures.

# --- WAPT agent: only /opt/wapt, extracted from the .deb without running its maintainer scripts
FROM debian:trixie-slim AS wapt
ARG WAPT_VERSION=2.7.0.19598-b35845cd
ARG WAPT_AGENT_SHA256=e128b9c5747735a6cf02cd93153e66f7f5ef1845aa557227f6a1adfda73cf6a6
RUN set -eux; \
    apt-get update; \
    DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends ca-certificates curl; \
    curl -fsSLo /tmp/agent.deb \
      "https://wapt.tranquil.it/wapt/releases/wapt-${WAPT_VERSION}/tis-waptagent-${WAPT_VERSION}-amd64.deb"; \
    echo "${WAPT_AGENT_SHA256}  /tmp/agent.deb" | sha256sum -c -; \
    dpkg-deb --fsys-tarfile /tmp/agent.deb | tar -x -C / ./opt/wapt; \
    rm -rf /opt/wapt/include

# --- Application
FROM debian:trixie-slim
RUN set -eux; \
    apt-get update; \
    DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends ca-certificates libatomic1 python3; \
    rm -rf /var/lib/apt/lists/*; \
    useradd --uid 10001 --home-dir /app --no-create-home app; \
    # audit journal; a named volume mounted here starts with this owner
    install -d -o 10001 -g 10001 -m 700 /data
COPY --from=wapt /opt/wapt /opt/wapt
COPY --from=ghcr.io/astral-sh/uv:0.11.31 /uv /usr/local/bin/uv

ENV UV_PYTHON_DOWNLOADS=never UV_PYTHON=/usr/bin/python3 UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/app/.venv PATH=/app/.venv/bin:$PATH
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY src/ src/
COPY signer/ signer/
RUN set -eux; \
    uv sync --frozen --no-dev; \
    # waptpython.sh expands $@ unquoted and runs with -I: script path only, sys.path set by the script
    printf 'import sys\nsys.path.insert(0, "/opt/wapt")\nimport waptcrypto, waptpackage, waptutils\n' > /tmp/check.py; \
    /opt/wapt/waptpython.sh /tmp/check.py; rm /tmp/check.py

USER app
EXPOSE 8000
# FORWARDED_ALLOW_IPS (read by uvicorn): address of the frontend nginx, the only proxy trusted for X-Forwarded-*
CMD ["uvicorn", "--factory", "wapt_webconsole.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers"]
