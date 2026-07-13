FROM python:3.12-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/ ./backend/
COPY web/ ./web/
COPY config/ ./config/
COPY tests/ ./tests/
COPY pyproject.toml .
COPY README.md .
COPY AGENTS.md .

RUN mkdir -p data

EXPOSE 8770

CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8770"]
