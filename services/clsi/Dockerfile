# Fleetex clsi service (Python port).
# Ships a TeX Live install + latexmk/synctex/texcount so the real compile path works.
FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    texlive-latex-base texlive-latex-extra texlive-fonts-recommended \
    latexmk texlive-extra-utils \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY services/_kit /app/_kit
COPY services/clsi /app/clsi
RUN pip install --no-cache-dir /app/_kit /app/clsi

EXPOSE 3013
ENV LISTEN_ADDRESS=0.0.0.0 PORT=3013 \
    CLSI_COMPILES_PATH=/app/clsi_data/compiles \
    CLSI_OUTPUT_PATH=/app/clsi_data/output \
    CLSI_CACHE_PATH=/app/clsi_data/cache
CMD ["python", "-m", "fleetex_clsi"]
