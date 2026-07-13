# Fleetex project-history service (Python port).
FROM python:3.12-slim

WORKDIR /app

COPY services/_kit /app/_kit
COPY services/project-history /app/project-history

RUN pip install --no-cache-dir /app/_kit /app/project-history

EXPOSE 3054
ENV LISTEN_ADDRESS=0.0.0.0 PORT=3054
CMD ["python", "-m", "fleetex_project_history"]
