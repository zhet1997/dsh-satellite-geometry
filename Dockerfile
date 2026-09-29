FROM node:22-bookworm-slim@sha256:43ac6c60b8f89723f746e8a92ce91abd5017e627ce1ddfe4238355d3a30b772c AS viewer
WORKDIR /build
COPY web/package*.json ./
RUN npm ci
COPY web/ ./
RUN npm run build

FROM python:3.12-slim-bookworm@sha256:392307d22300de8b5986851a12d9176dfc0fc073e65bf6523ebd7dcbeb23564e AS engine
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 SATCAD_DATA_ROOT=/data
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgl1 libglu1-mesa libglib2.0-0 libxrender1 libxext6 libsm6 libgomp1 \
    && rm -rf /var/lib/apt/lists/*
COPY requirements.lock /app/requirements.lock
RUN pip install --no-cache-dir -r /app/requirements.lock

FROM engine AS runtime
COPY service/ /app/service/
COPY vendor/ /app/vendor/
COPY --from=viewer /build/dist /app/web/dist
RUN groupadd --gid 10001 satcad && useradd --uid 10001 --gid satcad --create-home satcad \
    && mkdir -p /data && chown satcad:satcad /data
USER satcad
EXPOSE 8787
VOLUME ["/data"]
HEALTHCHECK --interval=30s --timeout=5s --start-period=45s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8787/api/health', timeout=4)"
CMD ["uvicorn", "service.app:app", "--host", "0.0.0.0", "--port", "8787", "--workers", "1"]
