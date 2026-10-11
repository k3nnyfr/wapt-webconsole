# Signature prototype: Debian 13 + waptpython of the WAPT Linux agent, extracted from the .deb without running
# its maintainer scripts (they enable systemd units and restart the agent service, useless in a container).
FROM debian:trixie-slim

ARG WAPT_VERSION=2.7.0.19598-b35845cd
ARG WAPT_AGENT_SHA256=e128b9c5747735a6cf02cd93153e66f7f5ef1845aa557227f6a1adfda73cf6a6

RUN set -eux; \
    apt-get update; \
    export DEBIAN_FRONTEND=noninteractive; \
    apt-get install -y --no-install-recommends ca-certificates curl libatomic1 python3; \
    curl -fsSLo /tmp/agent.deb \
      "https://wapt.tranquil.it/wapt/releases/wapt-${WAPT_VERSION}/tis-waptagent-${WAPT_VERSION}-amd64.deb"; \
    echo "${WAPT_AGENT_SHA256}  /tmp/agent.deb" | sha256sum -c -; \
    dpkg-deb --fsys-tarfile /tmp/agent.deb | tar -x -C / ./opt/wapt; \
    rm -rf /tmp/agent.deb /opt/wapt/include; \
    apt-get purge -y curl; apt-get autoremove -y; rm -rf /var/lib/apt/lists/*; \
    # waptpython.sh expands $@ unquoted: pass it a script path (no spaces), never -c "...".
    # It also runs Python with -I, so scripts add /opt/wapt to sys.path themselves.
    printf 'import sys\nsys.path.insert(0, "/opt/wapt")\nimport waptcrypto, waptpackage, waptutils\n' > /tmp/check.py; /opt/wapt/waptpython.sh /tmp/check.py; \
    rm /tmp/check.py; \
    useradd --system --uid 10001 --home-dir /app app

COPY signer/ /app/signer/
COPY proto/proto_signing.py /app/proto/

USER app
WORKDIR /app
ENTRYPOINT ["python3", "/app/proto/proto_signing.py"]
