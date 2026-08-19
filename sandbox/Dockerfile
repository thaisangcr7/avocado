# Analysis sandbox image.
#
# Contains exactly what generated analysis code is allowed to use: pandas,
# numpy, matplotlib. No shell utilities beyond what the base image needs, no
# network clients, no package manager left usable at runtime — containers from
# this image are started with --network=none and a read-only root filesystem,
# so there is nothing to fetch and nowhere to install it.
FROM python:3.12-slim

RUN pip install --no-cache-dir \
        pandas==2.2.3 \
        numpy==2.2.1 \
        matplotlib==3.10.0 \
 && rm -rf /root/.cache

# The runner is baked into the image rather than mounted, so the code being
# analysed cannot replace the harness that executes it.
COPY runner.py /opt/runner.py

# Unprivileged by default; the container is additionally started with
# --user, --cap-drop=ALL and --security-opt=no-new-privileges.
RUN useradd --uid 10001 --create-home --shell /usr/sbin/nologin sandboxrunner

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    MPLCONFIGDIR=/tmp/mpl \
    HOME=/tmp

USER 10001:10001
WORKDIR /tmp

ENTRYPOINT ["python", "/opt/runner.py"]
