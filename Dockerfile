FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY pyproject.toml README.md ./
COPY src ./src

FROM base AS dev

RUN pip install --no-cache-dir -e ".[dev]"

COPY tests ./tests

EXPOSE 8000

CMD ["uvicorn", "askhub_ai_server.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]

FROM base AS runtime

RUN pip install --no-cache-dir .

EXPOSE 8000

CMD ["uvicorn", "askhub_ai_server.main:app", "--host", "0.0.0.0", "--port", "8000"]
