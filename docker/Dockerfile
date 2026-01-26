FROM ghcr.io/astral-sh/uv:latest AS uv

FROM python:3.12-slim-bookworm
MAINTAINER rix1337

LABEL org.opencontainers.image.description="Quasarr connects JDownloader with Radarr, Sonarr and LazyLibrarian. It also decrypts links protected by CAPTCHAs."

# Define package name
ARG PACKAGE_NAME=quasarr

COPY --from=uv /uv /usr/local/bin/uv

# install local package
COPY dist/*.whl /tmp/

# Configure uv to install tools in globally accessible paths
ENV UV_TOOL_DIR=/opt/uv-tools
ENV UV_TOOL_BIN_DIR=/usr/local/bin

# The binary will now automatically appear in /usr/local/bin
RUN --mount=type=cache,target=/root/.cache/uv \
    uv tool install /tmp/*.whl --force && rm /tmp/*.whl

# volumes and ports
VOLUME /config
EXPOSE 8080
ENV PYTHONUNBUFFERED=1
ENV DOCKER="true"
ENV AUTH="form"
ENV USER=""
ENV PASS=""
ENV INTERNAL_ADDRESS=""
ENV EXTERNAL_ADDRESS=""
ENV DISCORD=""
ENV HOSTNAMES=""

# Restart loop: exit 0 = restart, exit non-zero = stop container
ENTRYPOINT ["sh", "-c", "while true; do quasarr --port=8080 --internal_address=$INTERNAL_ADDRESS --external_address=$EXTERNAL_ADDRESS --discord=$DISCORD --hostnames=$HOSTNAMES; ret=$?; if [ $ret -ne 0 ]; then echo \"Quasarr exited with error $ret, stopping...\"; exit $ret; fi; echo \"Quasarr restarting...\"; sleep 2; done"]
