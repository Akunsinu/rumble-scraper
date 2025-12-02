#!/bin/bash
# =============================================================================
# Rumble Scraper Docker Entrypoint Script
# =============================================================================
#
# This script handles:
# - Setting up proper file permissions (for Unraid)
# - Configuring cron for scheduled backups
# - Running initial backup on startup (if enabled)
# - Managing the cron daemon
#
# =============================================================================

set -e

# =============================================================================
# Configuration
# =============================================================================

# Default values (can be overridden by environment variables)
PUID=${PUID:-99}
PGID=${PGID:-100}
CONFIG_DIR=${CONFIG_DIR:-/config}
OUTPUT_DIR=${OUTPUT_DIR:-/data/rumble_backups}
LOG_DIR=${LOG_DIR:-/config/logs}
CRON_SCHEDULE=${CRON_SCHEDULE:-"0 2 * * *"}
RUN_ON_START=${RUN_ON_START:-true}
LOG_LEVEL=${LOG_LEVEL:-INFO}
BROWSER_COOKIES=${BROWSER_COOKIES:-}
COOKIES_FILE=${COOKIES_FILE:-}

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# =============================================================================
# Helper Functions
# =============================================================================

log_info() {
    echo -e "${GREEN}[INFO]${NC} $(date '+%Y-%m-%d %H:%M:%S') - $1"
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $(date '+%Y-%m-%d %H:%M:%S') - $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $(date '+%Y-%m-%d %H:%M:%S') - $1"
}

log_banner() {
    echo ""
    echo -e "${BLUE}============================================${NC}"
    echo -e "${BLUE}  Rumble Channel Backup${NC}"
    echo -e "${BLUE}============================================${NC}"
    echo ""
}

# =============================================================================
# Setup Functions
# =============================================================================

setup_permissions() {
    # Set up user/group permissions for Unraid compatibility
    log_info "Setting up permissions (PUID=$PUID, PGID=$PGID)"

    # Create group if it doesn't exist
    if ! getent group "$PGID" > /dev/null 2>&1; then
        groupadd -g "$PGID" rumble 2>/dev/null || true
    fi

    # Create user if it doesn't exist
    if ! getent passwd "$PUID" > /dev/null 2>&1; then
        useradd -u "$PUID" -g "$PGID" -d /config -s /bin/bash rumble 2>/dev/null || true
    fi

    # Set ownership of directories
    chown -R "$PUID:$PGID" /config 2>/dev/null || true
    chown -R "$PUID:$PGID" /data 2>/dev/null || true
    chown -R "$PUID:$PGID" /app 2>/dev/null || true

    log_info "Permissions configured successfully"
}

setup_directories() {
    # Ensure all required directories exist
    log_info "Setting up directories"

    mkdir -p "$CONFIG_DIR"
    mkdir -p "$LOG_DIR"
    mkdir -p "$OUTPUT_DIR"
    mkdir -p "$CONFIG_DIR/cache"

    # Create default config if it doesn't exist
    if [ ! -f "$CONFIG_DIR/config.json" ]; then
        log_info "Creating default configuration file"
        cat > "$CONFIG_DIR/config.json" << 'EOF'
{
  "_comment": "Rumble Channel Backup Configuration",
  "_instructions": "Add channel names to the 'channels' array below",
  "channels": [],
  "log_level": "INFO",
  "max_videos_per_channel": null,
  "force_rescan": false,
  "download_captions": true,
  "download_thumbnails": true
}
EOF
    fi

    log_info "Directories configured successfully"
}

setup_cron() {
    # Configure cron job for scheduled backups
    log_info "Setting up cron schedule: $CRON_SCHEDULE"

    # Create cron job file
    cat > /etc/cron.d/rumble-backup << EOF
# Rumble Channel Backup - Scheduled Task
# Schedule: $CRON_SCHEDULE
SHELL=/bin/bash
PATH=/opt/venv/bin:/usr/local/bin:/usr/bin:/bin
CONFIG_DIR=$CONFIG_DIR
OUTPUT_DIR=$OUTPUT_DIR
LOG_DIR=$LOG_DIR
LOG_LEVEL=$LOG_LEVEL
CHANNELS=$CHANNELS
MAX_VIDEOS=$MAX_VIDEOS
FORCE_RESCAN=$FORCE_RESCAN
BROWSER_COOKIES=$BROWSER_COOKIES
COOKIES_FILE=$COOKIES_FILE
XDG_CACHE_HOME=$CONFIG_DIR/cache

$CRON_SCHEDULE root /opt/venv/bin/python /app/rumble_scraper.py >> $LOG_DIR/cron.log 2>&1
EOF

    # Set proper permissions on cron file
    chmod 0644 /etc/cron.d/rumble-backup

    # Create empty log file if it doesn't exist
    touch "$LOG_DIR/cron.log"
    chown "$PUID:$PGID" "$LOG_DIR/cron.log"

    log_info "Cron job configured successfully"
}

print_configuration() {
    # Print current configuration
    log_banner

    echo "Configuration:"
    echo "  - Config Directory: $CONFIG_DIR"
    echo "  - Output Directory: $OUTPUT_DIR"
    echo "  - Log Directory: $LOG_DIR"
    echo "  - Log Level: $LOG_LEVEL"
    echo "  - Cron Schedule: $CRON_SCHEDULE"
    echo "  - Run on Start: $RUN_ON_START"
    echo "  - User ID (PUID): $PUID"
    echo "  - Group ID (PGID): $PGID"
    echo ""

    if [ -n "$CHANNELS" ]; then
        echo "  - Channels (env): $CHANNELS"
    else
        echo "  - Channels: (from config.json)"
    fi

    if [ -n "$MAX_VIDEOS" ]; then
        echo "  - Max Videos: $MAX_VIDEOS"
    fi

    if [ "$FORCE_RESCAN" = "true" ]; then
        echo "  - Force Rescan: ENABLED"
    fi

    echo ""
}

run_backup() {
    # Run the backup script
    log_info "Starting backup process..."

    # Export environment variables for the Python script
    export CONFIG_DIR
    export OUTPUT_DIR
    export LOG_DIR
    export LOG_LEVEL
    export CHANNELS
    export MAX_VIDEOS
    export FORCE_RESCAN
    export BROWSER_COOKIES
    export COOKIES_FILE
    export XDG_CACHE_HOME="$CONFIG_DIR/cache"

    # Run as the configured user (or root if user doesn't exist)
    if id -u "$PUID" > /dev/null 2>&1; then
        su - "$(id -nu "$PUID")" -s /bin/bash -c "cd /app && /opt/venv/bin/python /app/rumble_scraper.py"
    else
        /opt/venv/bin/python /app/rumble_scraper.py
    fi

    log_info "Backup process completed"
}

# =============================================================================
# Main Entry Point
# =============================================================================

main() {
    log_banner

    # Initial setup
    setup_directories
    setup_permissions
    setup_cron
    print_configuration

    # Check if channels are configured
    if [ -z "$CHANNELS" ]; then
        # Check if config.json has channels
        if [ -f "$CONFIG_DIR/config.json" ]; then
            CONFIG_CHANNELS=$(grep -o '"channels"[[:space:]]*:[[:space:]]*\[[^]]*\]' "$CONFIG_DIR/config.json" 2>/dev/null | grep -v '^\s*$' || echo "")
            if [ -z "$CONFIG_CHANNELS" ] || echo "$CONFIG_CHANNELS" | grep -q '\[\s*\]'; then
                log_warn "No channels configured!"
                log_warn "Add channels to config.json or set CHANNELS environment variable"
            fi
        fi
    fi

    # Run initial backup if enabled
    if [ "$RUN_ON_START" = "true" ]; then
        log_info "Running initial backup (RUN_ON_START=true)"
        run_backup || log_error "Initial backup encountered errors"
    else
        log_info "Skipping initial backup (RUN_ON_START=false)"
    fi

    # Start cron daemon in background
    log_info "Starting cron daemon for scheduled backups"
    log_info "Next backup scheduled according to: $CRON_SCHEDULE"
    cron

    # Start the web GUI or execute provided command
    if [ "$1" = "gunicorn" ] || [ -z "$1" ]; then
        log_info "Starting web GUI on port 4000"
        exec gunicorn --bind 0.0.0.0:4000 --workers 2 --access-logfile - --error-logfile - web_app:app
    else
        # Execute the provided command
        log_info "Executing command: $@"
        exec "$@"
    fi
}

# Run main function with all arguments
main "$@"
