FROM ghcr.io/home-assistant/base-python:3.14-alpine3.24

RUN pip install --no-cache-dir "gtfs-realtime-bindings==1.0.0" \
    && adduser -D -H -u 10001 bus

COPY run.py /app/run.py

# Run the poller as an unprivileged user; the Supervisor's /init handles S6.
CMD ["s6-setuidgid", "bus", "python3", "-u", "/app/run.py"]
