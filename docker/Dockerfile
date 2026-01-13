FROM alpine:latest
MAINTAINER rix1337

# Define package name
ARG PACKAGE_NAME=quasarr

RUN apk add --no-cache build-base \
    python3-dev \
    py3-pip

# setup
RUN mkdir -p ~/.config/pip && echo -e "[global]\nbreak-system-packages = true" > ~/.config/pip/pip.conf \
  && pip3 install --upgrade pip \
  && pip3 install wheel

# install local package
COPY dist/*.whl /tmp/
RUN pip install /tmp/*.whl && rm /tmp/*.whl && \
    apk del build-base

# volumes and ports
VOLUME /config
EXPOSE 8080
ENV PYTHONUNBUFFERED=1
ENV DOCKER="true"
ENV INTERNAL_ADDRESS=""
ENV EXTERNAL_ADDRESS=""
ENV DISCORD=""
ENV HOSTNAMES=""

# Restart loop: exit 0 = restart, exit non-zero = stop container
ENTRYPOINT ["sh", "-c", "while true; do quasarr --port=8080 --internal_address=$INTERNAL_ADDRESS --external_address=$EXTERNAL_ADDRESS --discord=$DISCORD --hostnames=$HOSTNAMES; ret=$?; if [ $ret -ne 0 ]; then echo \"Quasarr exited with error $ret, stopping...\"; exit $ret; fi; echo \"Quasarr restarting...\"; sleep 2; done"]
