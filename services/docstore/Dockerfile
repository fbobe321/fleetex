# Fleetex docstore service (Python port).
FROM python:3.12-slim

WORKDIR /app
COPY services/_kit /app/_kit
COPY services/docstore /app/docstore
RUN pip install --no-cache-dir /app/_kit /app/docstore

EXPOSE 3016
ENV LISTEN_ADDRESS=0.0.0.0 PORT=3016
CMD ["python", "-m", "fleetex_docstore"]
