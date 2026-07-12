# Fleetex filestore service (Python port, fs backend).
# imagemagick + optipng are included for the (currently unverified) conversion path.
FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    imagemagick optipng \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY services/_kit /app/_kit
COPY services/filestore /app/filestore
RUN pip install --no-cache-dir /app/_kit /app/filestore

EXPOSE 3009
ENV LISTEN_ADDRESS=0.0.0.0 PORT=3009 BACKEND=fs FILESTORE_PATH=/var/lib/overleaf/data/filestore
CMD ["python", "-m", "fleetex_filestore"]
