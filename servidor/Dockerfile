# Imagen de la API de ASI-ARCHIVO: Python, Tesseract (OCR) y cliente de antivirus.
# Se construye desde la raíz del repositorio:  docker compose -f servidor/docker-compose.yml build
FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/opt/asi/venv

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
       tesseract-ocr tesseract-ocr-eng tesseract-ocr-spa clamdscan tzdata ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:0.13.7 /uv /usr/local/bin/uv

WORKDIR /opt/asi
# Solo lo necesario para el servidor (sin pruebas, documentos ni herramientas).
COPY pyproject.toml uv.lock ./
COPY shared ./shared
COPY server ./server
COPY client/pyproject.toml ./client/pyproject.toml
COPY client/asi_cliente/__init__.py ./client/asi_cliente/__init__.py
RUN uv sync --frozen --no-dev --package asi-server

COPY servidor/antivirus/asi-antivirus /usr/local/bin/asi-antivirus
COPY servidor/antivirus/clamd-cliente.conf /etc/clamav/clamd-cliente.conf
COPY servidor/entrada.py /opt/asi/entrada.py
RUN chmod 755 /usr/local/bin/asi-antivirus \
    && groupadd --gid 10001 asi \
    && useradd --system --uid 10001 --gid 10001 --home /nonexistent --shell /usr/sbin/nologin asi \
    && mkdir -p /datos/documentos && chown asi:asi /datos/documentos && chmod 700 /datos/documentos

USER asi
WORKDIR /opt/asi/server
ENV PATH=/opt/asi/venv/bin:$PATH
EXPOSE 8000
ENTRYPOINT ["python", "/opt/asi/entrada.py"]
# Detrás del proxy HTTPS: se confía en su encabezado X-Forwarded-For para conocer la
# IP real de cada computadora (el límite de intentos de acceso se cuenta por IP).
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2", \
     "--proxy-headers", "--forwarded-allow-ips", "*", "--no-access-log"]
