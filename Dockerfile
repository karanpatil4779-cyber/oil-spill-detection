FROM python:3.11-slim

WORKDIR /app

# Runtime libs needed by numpy / rasterio wheels (manylinux wheels bundle GDAL/GEOS/PROJ).
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgomp1 \
    && rm -rf /var/lib/apt/lists/*

# Lean runtime deps (torch/torchvision/cdsapi/copernicusmarine are training/download-only and are NOT installed).
COPY requirements-render.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements-render.txt

COPY . .

ENV PYTHONPATH=/app
ENV PORT=10000
ENV DATABASE_URL=""

EXPOSE 10000

HEALTHCHECK --interval=30s --timeout=5s --start-period=60s \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:10000/health', timeout=4) or exit(1)" || exit 1

CMD ["uvicorn", "apps.api.main:app", "--host", "0.0.0.0", "--port", "10000"]