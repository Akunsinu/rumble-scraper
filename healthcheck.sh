#!/bin/bash
# =============================================================================
# Healthcheck Script for Rumble Scraper Container
# =============================================================================
#
# This script verifies the container is running properly by checking:
# - Required directories exist and are writable
# - Python environment is functional
# - Cron service is running (if in scheduled mode)
#
# Exit codes:
#   0 = Healthy
#   1 = Unhealthy
#
# =============================================================================

# Configuration
CONFIG_DIR=${CONFIG_DIR:-/config}
OUTPUT_DIR=${OUTPUT_DIR:-/data/rumble_backups}
LOG_DIR=${LOG_DIR:-/config/logs}

# Check if config directory exists and is writable
if [ ! -d "$CONFIG_DIR" ]; then
    echo "UNHEALTHY: Config directory does not exist: $CONFIG_DIR"
    exit 1
fi

if [ ! -w "$CONFIG_DIR" ]; then
    echo "UNHEALTHY: Config directory is not writable: $CONFIG_DIR"
    exit 1
fi

# Check if output directory exists and is writable
if [ ! -d "$OUTPUT_DIR" ]; then
    echo "UNHEALTHY: Output directory does not exist: $OUTPUT_DIR"
    exit 1
fi

if [ ! -w "$OUTPUT_DIR" ]; then
    echo "UNHEALTHY: Output directory is not writable: $OUTPUT_DIR"
    exit 1
fi

# Check if Python is working
if ! /opt/venv/bin/python --version > /dev/null 2>&1; then
    echo "UNHEALTHY: Python is not functional"
    exit 1
fi

# Check if required Python modules are importable
if ! /opt/venv/bin/python -c "import yt_dlp, requests, bs4" 2>/dev/null; then
    echo "UNHEALTHY: Required Python modules not available"
    exit 1
fi

# Check if cron is running (if we're in daemon mode)
if pgrep cron > /dev/null 2>&1 || pgrep crond > /dev/null 2>&1; then
    echo "HEALTHY: Cron daemon is running"
else
    # Cron might not be running if we're in single-run mode, which is OK
    echo "HEALTHY: Container operational (cron not running - may be single-run mode)"
fi

exit 0
