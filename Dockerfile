ARG PYTHON_IMAGE=python:3.13-slim
FROM ${PYTHON_IMAGE} AS dependencies
WORKDIR /app
COPY requirements.lock ./
RUN python -m venv /opt/venv \
    && /opt/venv/bin/pip install --no-cache-dir --require-hashes -r requirements.lock

FROM ${PYTHON_IMAGE} AS runtime
ENV PATH="/opt/venv/bin:$PATH" PYTHONPATH=/app/src \
    PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY --from=dependencies /opt/venv /opt/venv
COPY src ./src
COPY scripts ./scripts
COPY migrations ./migrations
COPY config ./config
COPY dashboard ./dashboard
RUN useradd --create-home --uid 10001 tokenos
USER tokenos
EXPOSE 8000
CMD ["uvicorn", "tokenos.interfaces.api:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]

