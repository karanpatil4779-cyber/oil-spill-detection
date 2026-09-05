FROM python:3.11-slim

WORKDIR /app

# System deps required by geospatial + data-science wheels
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libgomp1 \
    libgdal-dev \
    gdal-bin \
    libgeos-dev \
    libproj-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt && \
    pip install --no-cache-dir httpx

COPY . .

ENV PYTHONPATH=/app
ENV PORT=10000

EXPOSE 10000

CMD ["uvicorn", "apps.api.main:app", "--host", "0.0.0.0", "--port", "10000"]
