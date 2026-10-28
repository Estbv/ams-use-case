FROM python:3.11-slim

WORKDIR /app

# Dependencias del sistema
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl && \
    rm -rf /var/lib/apt/lists/*

# Copiar requirements e instalar
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copiar el codigo
COPY app/ ./app/
COPY data/ ./data/
COPY samples/ ./samples/
COPY pytest.ini .

# Directorio para expedientes
RUN mkdir -p cases && chmod 777 cases

# Usuario no root
RUN useradd -m -u 1000 ams
USER ams

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
