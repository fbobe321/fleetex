# Fleetex document-updater service (Python port, OT engine).
FROM python:3.12-slim

WORKDIR /app
COPY services/_kit /app/_kit
COPY services/document-updater /app/document-updater
RUN pip install --no-cache-dir /app/_kit /app/document-updater

EXPOSE 3003
ENV LISTEN_ADDRESS=0.0.0.0 PORT=3003
CMD ["python", "-m", "fleetex_document_updater"]
