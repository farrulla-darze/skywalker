# Skywalker API image
FROM python:3.12-slim

WORKDIR /app

RUN pip install --no-cache-dir poetry poetry-plugin-export

# Dependency layer (cached)
COPY pyproject.toml poetry.lock* ./
RUN poetry export --without-hashes -f requirements.txt -o /tmp/requirements.txt \
    && pip install --no-cache-dir -r /tmp/requirements.txt

# Application code + runtime assets (self-contained image — no bind mounts required)
COPY app ./app
COPY db ./db

EXPOSE 8000

HEALTHCHECK --interval=10s --timeout=5s --retries=5 --start-period=20s \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')"

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
