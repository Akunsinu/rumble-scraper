#!/usr/bin/env python3
"""
Rumble Scraper Web GUI
======================
Flask-based web interface for managing Rumble channel backups.
"""

import os
import json
import subprocess
import threading
import time
from datetime import datetime
from pathlib import Path
from functools import wraps

from flask import Flask, render_template, request, jsonify, redirect, url_for, send_from_directory, Response

# =============================================================================
# Configuration
# =============================================================================

app = Flask(__name__, template_folder='templates', static_folder='static')
app.secret_key = os.environ.get('SECRET_KEY', 'rumble-scraper-secret-key-change-me')

CONFIG_DIR = Path(os.environ.get('CONFIG_DIR', '/config'))
OUTPUT_DIR = Path(os.environ.get('OUTPUT_DIR', '/data/rumble_backups'))
LOG_DIR = Path(os.environ.get('LOG_DIR', '/config/logs'))

# Backup process state
backup_process = {
    'running': False,
    'pid': None,
    'started_at': None,
    'channel': None
}

# =============================================================================
# Helper Functions
# =============================================================================

def get_config():
    """Load configuration from file."""
    config_file = CONFIG_DIR / 'config.json'
    default_config = {
        'channels': [],
        'log_level': 'INFO',
        'max_videos_per_channel': None,
        'force_rescan': False,
        'browser_cookies': None,
        'cookies_file': None
    }

    if config_file.exists():
        try:
            with open(config_file, 'r') as f:
                user_config = json.load(f)
                default_config.update(user_config)
        except (json.JSONDecodeError, IOError):
            pass

    # Override with environment variables
    if os.environ.get('CHANNELS'):
        default_config['channels'] = os.environ['CHANNELS'].split(',')
    if os.environ.get('BROWSER_COOKIES'):
        default_config['browser_cookies'] = os.environ['BROWSER_COOKIES']

    return default_config


def save_config(config):
    """Save configuration to file."""
    config_file = CONFIG_DIR / 'config.json'
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    with open(config_file, 'w') as f:
        json.dump(config, f, indent=2)


def get_backup_state():
    """Load backup state from file."""
    state_file = CONFIG_DIR / 'backup_state.json'
    if state_file.exists():
        try:
            with open(state_file, 'r') as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            pass
    return {'channels': {}, 'last_run': None}


def get_channels_status():
    """Get status for all channels."""
    config = get_config()
    state = get_backup_state()
    channels_status = []

    for channel in config.get('channels', []):
        channel = channel.strip()
        if not channel:
            continue

        channel_state = state.get('channels', {}).get(channel, {})
        channel_dir = OUTPUT_DIR / channel.replace('/', '_').replace(':', '_')

        # Count videos
        video_count = 0
        total_size = 0
        if channel_dir.exists():
            for video_dir in channel_dir.iterdir():
                if video_dir.is_dir():
                    video_count += 1
                    for f in video_dir.iterdir():
                        if f.is_file():
                            total_size += f.stat().st_size

        channels_status.append({
            'name': channel,
            'video_count': video_count,
            'total_size': format_size(total_size),
            'last_backup': channel_state.get('last_backup'),
            'downloaded_count': len(channel_state.get('downloaded_videos', []))
        })

    return channels_status


def get_channel_videos(channel_name):
    """Get list of videos for a channel."""
    safe_name = channel_name.replace('/', '_').replace(':', '_')
    channel_dir = OUTPUT_DIR / safe_name
    videos = []

    if not channel_dir.exists():
        return videos

    for video_dir in sorted(channel_dir.iterdir(), key=lambda x: x.stat().st_mtime, reverse=True):
        if not video_dir.is_dir():
            continue

        video_id = video_dir.name
        metadata_file = video_dir / 'metadata.json'
        info_file = video_dir / f'{video_id}.info.json'

        video_info = {
            'id': video_id,
            'title': video_id,
            'thumbnail': None,
            'duration': None,
            'views': None,
            'upload_date': None,
            'has_video': False
        }

        # Load metadata
        if metadata_file.exists():
            try:
                with open(metadata_file, 'r') as f:
                    meta = json.load(f)
                    video_info.update({
                        'title': meta.get('title', video_id),
                        'duration': meta.get('duration'),
                        'views': meta.get('view_count'),
                        'upload_date': meta.get('upload_date'),
                        'description': meta.get('description', '')[:200]
                    })
            except:
                pass
        elif info_file.exists():
            try:
                with open(info_file, 'r') as f:
                    meta = json.load(f)
                    video_info.update({
                        'title': meta.get('title', video_id),
                        'duration': meta.get('duration'),
                        'views': meta.get('view_count'),
                        'upload_date': meta.get('upload_date'),
                        'description': meta.get('description', '')[:200]
                    })
            except:
                pass

        # Check for video file
        for ext in ['mp4', 'webm', 'mkv']:
            video_file = video_dir / f'{video_id}.{ext}'
            if video_file.exists():
                video_info['has_video'] = True
                video_info['video_ext'] = ext
                video_info['video_size'] = format_size(video_file.stat().st_size)
                break

        # Check for thumbnail
        for ext in ['jpg', 'jpeg', 'png', 'webp']:
            thumb_file = video_dir / f'{video_id}.{ext}'
            if thumb_file.exists():
                video_info['thumbnail'] = f'/video/{channel_name}/{video_id}/thumbnail'
                break

        videos.append(video_info)

    return videos


def format_size(size_bytes):
    """Format bytes to human readable size."""
    for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
        if size_bytes < 1024.0:
            return f"{size_bytes:.1f} {unit}"
        size_bytes /= 1024.0
    return f"{size_bytes:.1f} PB"


def format_duration(seconds):
    """Format seconds to HH:MM:SS."""
    if not seconds:
        return '--:--'
    hours, remainder = divmod(int(seconds), 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"


def get_logs(lines=100):
    """Get recent log entries."""
    log_file = LOG_DIR / 'rumble_scraper.log'
    cron_log = LOG_DIR / 'cron.log'

    logs = []

    for lf in [log_file, cron_log]:
        if lf.exists():
            try:
                with open(lf, 'r') as f:
                    content = f.readlines()
                    logs.extend(content[-lines:])
            except:
                pass

    # Sort by timestamp if possible
    logs.sort(reverse=True)
    return logs[:lines]


def run_backup_async(channel=None):
    """Run backup in background thread."""
    global backup_process

    if backup_process['running']:
        return False

    def run():
        global backup_process
        backup_process['running'] = True
        backup_process['started_at'] = datetime.now().isoformat()
        backup_process['channel'] = channel

        try:
            env = os.environ.copy()
            if channel:
                env['CHANNELS'] = channel

            result = subprocess.run(
                ['python', '/app/rumble_scraper.py'],
                env=env,
                capture_output=True,
                text=True,
                cwd='/app'
            )

            # Log output
            log_file = LOG_DIR / 'rumble_scraper.log'
            with open(log_file, 'a') as f:
                f.write(result.stdout)
                if result.stderr:
                    f.write(result.stderr)

        except Exception as e:
            log_file = LOG_DIR / 'rumble_scraper.log'
            with open(log_file, 'a') as f:
                f.write(f"Error running backup: {e}\n")
        finally:
            backup_process['running'] = False
            backup_process['pid'] = None
            backup_process['channel'] = None

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    return True


# =============================================================================
# Template Filters
# =============================================================================

@app.template_filter('format_duration')
def format_duration_filter(seconds):
    return format_duration(seconds)


@app.template_filter('format_date')
def format_date_filter(date_str):
    if not date_str:
        return 'Unknown'
    try:
        if len(date_str) == 8:  # YYYYMMDD format
            dt = datetime.strptime(date_str, '%Y%m%d')
            return dt.strftime('%b %d, %Y')
        else:
            dt = datetime.fromisoformat(date_str.replace('Z', '+00:00'))
            return dt.strftime('%b %d, %Y %H:%M')
    except:
        return date_str


@app.template_filter('format_number')
def format_number_filter(num):
    if not num:
        return '--'
    if num >= 1000000:
        return f"{num/1000000:.1f}M"
    if num >= 1000:
        return f"{num/1000:.1f}K"
    return str(num)


# =============================================================================
# Routes - Pages
# =============================================================================

@app.route('/')
def index():
    """Dashboard page."""
    channels = get_channels_status()
    state = get_backup_state()
    config = get_config()

    total_videos = sum(c['video_count'] for c in channels)

    return render_template('index.html',
        channels=channels,
        total_videos=total_videos,
        last_run=state.get('last_run'),
        backup_running=backup_process['running'],
        backup_channel=backup_process.get('channel'),
        cron_schedule=os.environ.get('CRON_SCHEDULE', '0 2 * * *')
    )


@app.route('/channels')
def channels_page():
    """Channel management page."""
    channels = get_channels_status()
    return render_template('channels.html', channels=channels)


@app.route('/channel/<path:channel_name>')
def channel_detail(channel_name):
    """Channel detail with video list."""
    videos = get_channel_videos(channel_name)
    return render_template('channel_detail.html',
        channel_name=channel_name,
        videos=videos,
        video_count=len(videos)
    )


@app.route('/settings')
def settings_page():
    """Settings page."""
    config = get_config()
    return render_template('settings.html', config=config)


@app.route('/logs')
def logs_page():
    """Logs viewer page."""
    logs = get_logs(200)
    return render_template('logs.html', logs=logs)


# =============================================================================
# Routes - API
# =============================================================================

@app.route('/api/status')
def api_status():
    """Get current status."""
    channels = get_channels_status()
    state = get_backup_state()

    return jsonify({
        'backup_running': backup_process['running'],
        'backup_channel': backup_process.get('channel'),
        'backup_started': backup_process.get('started_at'),
        'last_run': state.get('last_run'),
        'channel_count': len(channels),
        'total_videos': sum(c['video_count'] for c in channels)
    })


@app.route('/api/channels', methods=['GET'])
def api_get_channels():
    """Get all channels."""
    return jsonify(get_channels_status())


@app.route('/api/channels', methods=['POST'])
def api_add_channel():
    """Add a new channel."""
    data = request.json
    channel = data.get('channel', '').strip()

    if not channel:
        return jsonify({'error': 'Channel name required'}), 400

    config = get_config()
    if channel not in config['channels']:
        config['channels'].append(channel)
        save_config(config)

    return jsonify({'success': True, 'channel': channel})


@app.route('/api/channels/<path:channel_name>', methods=['DELETE'])
def api_delete_channel(channel_name):
    """Remove a channel."""
    config = get_config()
    if channel_name in config['channels']:
        config['channels'].remove(channel_name)
        save_config(config)

    return jsonify({'success': True})


@app.route('/api/backup', methods=['POST'])
def api_start_backup():
    """Start a backup."""
    data = request.json or {}
    channel = data.get('channel')

    if backup_process['running']:
        return jsonify({'error': 'Backup already running'}), 409

    success = run_backup_async(channel)
    return jsonify({'success': success})


@app.route('/api/settings', methods=['GET'])
def api_get_settings():
    """Get settings."""
    return jsonify(get_config())


@app.route('/api/settings', methods=['POST'])
def api_save_settings():
    """Save settings."""
    data = request.json
    config = get_config()

    # Update allowed fields
    for field in ['log_level', 'max_videos_per_channel', 'force_rescan', 'browser_cookies']:
        if field in data:
            config[field] = data[field]

    save_config(config)
    return jsonify({'success': True})


@app.route('/api/logs')
def api_get_logs():
    """Get logs."""
    lines = request.args.get('lines', 100, type=int)
    logs = get_logs(lines)
    return jsonify({'logs': logs})


# =============================================================================
# Routes - Video Serving
# =============================================================================

@app.route('/video/<path:channel_name>/<video_id>/play')
def video_play(channel_name, video_id):
    """Video player page."""
    safe_channel = channel_name.replace('/', '_').replace(':', '_')
    video_dir = OUTPUT_DIR / safe_channel / video_id

    video_info = {'id': video_id, 'title': video_id}

    # Load metadata
    metadata_file = video_dir / 'metadata.json'
    info_file = video_dir / f'{video_id}.info.json'

    for mf in [metadata_file, info_file]:
        if mf.exists():
            try:
                with open(mf, 'r') as f:
                    video_info.update(json.load(f))
                break
            except:
                pass

    # Find video file
    video_url = None
    for ext in ['mp4', 'webm', 'mkv']:
        if (video_dir / f'{video_id}.{ext}').exists():
            video_url = f'/video/{channel_name}/{video_id}/stream.{ext}'
            break

    return render_template('player.html',
        video=video_info,
        video_url=video_url,
        channel_name=channel_name
    )


@app.route('/video/<path:channel_name>/<video_id>/stream.<ext>')
def video_stream(channel_name, video_id, ext):
    """Stream video file."""
    safe_channel = channel_name.replace('/', '_').replace(':', '_')
    video_dir = OUTPUT_DIR / safe_channel / video_id
    video_file = video_dir / f'{video_id}.{ext}'

    if not video_file.exists():
        return "Video not found", 404

    return send_from_directory(video_dir, f'{video_id}.{ext}')


@app.route('/video/<path:channel_name>/<video_id>/thumbnail')
def video_thumbnail(channel_name, video_id):
    """Serve video thumbnail."""
    safe_channel = channel_name.replace('/', '_').replace(':', '_')
    video_dir = OUTPUT_DIR / safe_channel / video_id

    for ext in ['jpg', 'jpeg', 'png', 'webp']:
        thumb_file = video_dir / f'{video_id}.{ext}'
        if thumb_file.exists():
            return send_from_directory(video_dir, f'{video_id}.{ext}')

    # Return placeholder
    return "", 404


# =============================================================================
# Main
# =============================================================================

if __name__ == '__main__':
    # Ensure directories exist
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    # Run Flask
    port = int(os.environ.get('WEB_PORT', 4000))
    debug = os.environ.get('FLASK_DEBUG', 'false').lower() == 'true'

    app.run(host='0.0.0.0', port=port, debug=debug)
