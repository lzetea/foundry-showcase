# Use a pinned slim base image
FROM python:3.12-slim

# Create non-root user
RUN groupadd --system app && useradd --system --gid app --create-home --home-dir /home/app app

WORKDIR /app

# Install deps first for layer caching
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip \
 && pip install --no-cache-dir -r requirements.txt

# Copy app and data
COPY . .
COPY data/ ./data/

# Drop privileges
RUN chown -R app:app /app
USER app

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

EXPOSE 8088

HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
  CMD python -c "import socket,sys; s=socket.socket(); s.settimeout(3); \
s.connect(('127.0.0.1',8088)); sys.exit(0)" || exit 1

CMD ["python", "agent_app.py"]
