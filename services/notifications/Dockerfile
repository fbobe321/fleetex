# Fleetex notifications service (Python port).
FROM python:3.12-slim

WORKDIR /app

# The kit is a path dependency; copy both and install.
COPY services/_kit /app/_kit
COPY services/notifications /app/notifications

RUN pip install --no-cache-dir /app/_kit /app/notifications

EXPOSE 3042
ENV LISTEN_ADDRESS=0.0.0.0 PORT=3042
CMD ["python", "-m", "fleetex_notifications"]
