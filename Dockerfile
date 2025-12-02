# =============================================================================
# Rumble Channel Backup Docker Image
# =============================================================================
# Multi-stage build for efficient image size
# Based on Python 3.11 slim for smaller footprint
#
# Features:
# - yt-dlp for video downloading
# - FFmpeg for video processing
# - BeautifulSoup for web scraping
# - Cron support for scheduled backups
# =============================================================================

# -----------------------------------------------------------------------------
# Stage 1: Builder - Install Python dependencies
# -----------------------------------------------------------------------------
FROM python:3.11-slim-bookworm AS builder

# Prevent Python from writing bytecode and buffering stdout/stderr
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# Install build dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libffi-dev \
    && rm -rf /var/lib/apt/lists/*

# Create virtual environment
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt


# -----------------------------------------------------------------------------
# Stage 2: Runtime - Final image
# -----------------------------------------------------------------------------
FROM python:3.11-slim-bookworm

# Image metadata
LABEL maintainer="Rumble Scraper" \
      description="Automated Rumble channel backup with metadata, comments, and captions" \
      version="1.0.0"

# Environment configuration
# These can be overridden at runtime
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    # Application directories
    CONFIG_DIR=/config \
    OUTPUT_DIR=/data/rumble_backups \
    LOG_DIR=/config/logs \
    # Default settings
    LOG_LEVEL=INFO \
    CRON_SCHEDULE="0 2 * * *" \
    TZ=America/New_York \
    # yt-dlp cache directory
    XDG_CACHE_HOME=/config/cache

# Install runtime dependencies
# - ffmpeg: Required for video processing and merging
# - cron: For scheduled backups
# - tzdata: For timezone support
# - curl: For healthchecks
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    cron \
    tzdata \
    curl \
    && rm -rf /var/lib/apt/lists/* \
    && apt-get clean

# Copy virtual environment from builder
COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Create application directories
# /app - Application code
# /config - Configuration files and state
# /data - Video backup storage
RUN mkdir -p /app /config /config/logs /config/cache /data/rumble_backups

# Set working directory
WORKDIR /app

# Copy application files
COPY rumble_scraper.py /app/
COPY web_app.py /app/
COPY entrypoint.sh /app/
COPY healthcheck.sh /app/
COPY templates /app/templates
COPY static /app/static

# Make scripts executable
RUN chmod +x /app/entrypoint.sh /app/healthcheck.sh /app/rumble_scraper.py

# Create non-root user for security
# Using UID 99 and GID 100 for Unraid compatibility (nobody:users)
RUN groupadd -g 100 rumble || true && \
    useradd -u 99 -g 100 -d /config -s /bin/bash rumble || true

# Set ownership of application directories
RUN chown -R 99:100 /app /config /data

# Volume mount points
# /config - Persistent configuration (mount to appdata)
# /data - Backup storage (mount to your media share)
VOLUME ["/config", "/data"]

# Expose web GUI port
EXPOSE 4000

# Healthcheck to verify the container is running properly
HEALTHCHECK --interval=5m --timeout=30s --start-period=10s --retries=3 \
    CMD /app/healthcheck.sh

# Use the entrypoint script for initialization
ENTRYPOINT ["/app/entrypoint.sh"]

# Default command - start web GUI with gunicorn
CMD ["gunicorn", "--bind", "0.0.0.0:4000", "--workers", "2", "web_app:app"]
