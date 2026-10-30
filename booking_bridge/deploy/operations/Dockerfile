ARG BASE_IMAGE=sha256:7b11e4fbc5c7335e763677909243553f38f050ead7101271aec723c06c7210b9
FROM ${BASE_IMAGE}
USER root
COPY booking_bridge/deploy/operations/requirements.lock.txt /tmp/operations-requirements.txt
RUN python -m pip install --no-cache-dir --no-deps -r /tmp/operations-requirements.txt
COPY booking_bridge/deploy/offhost_backup.py /app/booking_bridge/deploy/offhost_backup.py
COPY booking_bridge/deploy/operations_monitor.py /app/booking_bridge/deploy/operations_monitor.py
RUN mkdir -p /backup-spool /monitor-state && chown 10001:10001 /backup-spool /monitor-state && chmod 700 /backup-spool /monitor-state
USER 10001:10001
WORKDIR /app
