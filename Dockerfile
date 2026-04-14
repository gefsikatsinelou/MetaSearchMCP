FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    HOST=0.0.0.0 \
    PORT=8000

WORKDIR /app

COPY pyproject.toml README.md LICENSE ./
COPY metasearchmcp ./metasearchmcp

RUN pip install .

EXPOSE 8000

CMD ["python", "-m", "metasearchmcp.server"]
