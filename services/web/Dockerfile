# Fleetex web service (Python port, auth slice).
FROM python:3.12-slim

WORKDIR /app
COPY services/_kit /app/_kit
COPY services/web /app/web
RUN pip install --no-cache-dir /app/_kit /app/web

EXPOSE 3000
ENV LISTEN_ADDRESS=0.0.0.0 PORT=3000
CMD ["python", "-m", "fleetex_web"]
