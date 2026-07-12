# Fleetex chat service (Python port).
FROM python:3.12-slim

WORKDIR /app

COPY services/_kit /app/_kit
COPY services/chat /app/chat

RUN pip install --no-cache-dir /app/_kit /app/chat

EXPOSE 3010
ENV LISTEN_ADDRESS=0.0.0.0 PORT=3010
CMD ["python", "-m", "fleetex_chat"]
