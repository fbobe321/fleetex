# Fleetex real-time service (Python port).
FROM python:3.12-slim

WORKDIR /app
COPY services/_kit /app/_kit
COPY services/real-time /app/real-time
RUN pip install --no-cache-dir /app/_kit /app/real-time

EXPOSE 3026
ENV LISTEN_ADDRESS=0.0.0.0 PORT=3026
CMD ["python", "-m", "fleetex_realtime"]
