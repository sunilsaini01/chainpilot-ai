FROM python:3.11-slim

# No .pyc files in the image; logs flushed immediately so `docker logs` is live.
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Security updates for the operating system packages of the base image, so a fix
# Debian publishes is in the next build (ECR's scan lists what is still open).
RUN apt-get update && apt-get upgrade -y && rm -rf /var/lib/apt/lists/*

# Install dependencies first so this layer is cached when only code changes.
COPY requirements.txt .
RUN pip install -r requirements.txt

COPY app ./app
# Policy documents for the AI copilot (loaded with `python -m app.cli load-policies`).
COPY policies ./policies
# Migrations ship in the same image; the Compose `migrate` service runs them.
COPY alembic.ini .
COPY migrations ./migrations

# Run as an unprivileged user rather than root.
RUN useradd --create-home --uid 10001 appuser
USER appuser

EXPOSE 8000

# Uses Python instead of curl, which the slim image does not include.
HEALTHCHECK --interval=10s --timeout=3s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=2)"

# --no-server-header: answers do not name the server software (P8-T3-R1).
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--no-server-header"]
