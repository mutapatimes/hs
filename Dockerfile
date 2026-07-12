# Halia web service image. We use Docker (rather than Render's native Python runtime) because
# WeasyPrint — the catalog-PDF generator — needs the cairo / pango / gdk-pixbuf system libraries,
# which can't be apt-installed on the native runtime. Everything else about the app is unchanged.
FROM python:3.11-slim

# WeasyPrint runtime libraries + a couple of font families so generated catalogs render text.
# ca-certificates: the slim base ships none, so any TLS fetch (incl. WeasyPrint's own image
# fetcher) fails cert verification without it — catalogue product images come out blank.
RUN apt-get update && apt-get install -y --no-install-recommends \
      libpango-1.0-0 libpangocairo-1.0-0 libcairo2 libgdk-pixbuf-2.0-0 \
      libffi8 shared-mime-info fonts-dejavu fonts-liberation ca-certificates \
    && rm -rf /var/lib/apt/lists/*

ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .

# Render provides $PORT; default to 8000 for local `docker run`.
ENV PORT=8000
CMD ["sh", "-c", "uvicorn halia.api.app:app --host 0.0.0.0 --port ${PORT}"]
