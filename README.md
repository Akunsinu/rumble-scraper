# Rumble Channel Backup for Unraid

Automatically backup Rumble channels with videos, metadata, thumbnails, and subtitles. Includes a web GUI for easy management.

## ⚠️ Important: Cloudflare Protection

Rumble uses Cloudflare protection that blocks requests from certain IP addresses. If you get 403 errors:

1. **Deploy to Unraid** - Your server's IP may work when your local machine doesn't
2. **Use browser cookies** - Set `BROWSER_COOKIES=chrome` (or `firefox`)
3. **Use a VPN** - Change your IP address
4. **Wait** - Blocks are sometimes temporary

This is a known issue: [yt-dlp #15148](https://github.com/yt-dlp/yt-dlp/issues/15148)

## Features

- **Web GUI** - Add/remove channels, trigger backups, browse videos, view logs
- Downloads videos in best quality (MP4)
- Saves metadata (title, description, views, likes, date, duration)
- Downloads thumbnails and subtitles when available
- Incremental backups (skips already downloaded videos)
- Scheduled backups via cron
- Uses `--impersonate chrome` for Cloudflare bypass

## Quick Start

### Option 1: Docker Compose

```bash
# Create directory
mkdir -p /mnt/user/appdata/rumble-scraper
cd /mnt/user/appdata/rumble-scraper

# Create .env file
cat > .env << 'EOF'
CHANNELS=YourChannel1,YourChannel2
BROWSER_COOKIES=chrome
CRON_SCHEDULE=0 2 * * *
TZ=America/New_York
CONFIG_PATH=/mnt/user/appdata/rumble-scraper
DATA_PATH=/mnt/user/media/rumble_backups
EOF

# Copy docker-compose.yml and run
docker-compose up -d
```

### Option 2: Docker Run

```bash
docker run -d \
  --name rumble-scraper \
  -p 4000:4000 \
  -e CHANNELS="ChannelName" \
  -e BROWSER_COOKIES="chrome" \
  -e CRON_SCHEDULE="0 2 * * *" \
  -e TZ="America/New_York" \
  -e PUID=99 \
  -e PGID=100 \
  -v /mnt/user/appdata/rumble-scraper:/config \
  -v /mnt/user/media/rumble_backups:/data \
  rumble-scraper
```

Then open http://your-server-ip:4000 in your browser.

### Option 3: Local Python

```bash
# Install
pip install "yt-dlp[curl_cffi]"

# Run
CHANNELS="ChannelName" \
BROWSER_COOKIES="chrome" \
OUTPUT_DIR="./backups" \
CONFIG_DIR="./config" \
python rumble_scraper.py
```

## Configuration

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `CHANNELS` | (required) | Comma-separated channel names or URLs |
| `BROWSER_COOKIES` | none | Browser for cookies: `chrome`, `firefox`, `edge` |
| `COOKIES_FILE` | none | Path to cookies.txt file |
| `CRON_SCHEDULE` | `0 2 * * *` | Backup schedule |
| `RUN_ON_START` | `true` | Run backup on container start |
| `MAX_VIDEOS` | unlimited | Max videos per channel |
| `FORCE_RESCAN` | `false` | Re-download all videos |
| `LOG_LEVEL` | `INFO` | Logging verbosity |
| `TZ` | `America/New_York` | Timezone |
| `PUID` | `99` | User ID (Unraid default) |
| `PGID` | `100` | Group ID (Unraid default) |
| `WEB_PORT` | `4000` | Web GUI port |

### Channel Formats

All these work:
```
ChannelName
c/ChannelName
https://rumble.com/c/ChannelName
user/Username
```

### Config File

Edit `/config/config.json`:

```json
{
  "channels": ["Channel1", "Channel2"],
  "browser_cookies": "chrome",
  "max_videos_per_channel": null,
  "force_rescan": false,
  "log_level": "INFO"
}
```

## Web GUI

Access the web interface at `http://your-server-ip:4000`

Features:
- **Dashboard** - Overview of all channels and backup status
- **Channels** - Add, remove, and manage channels
- **Video Browser** - Browse and play downloaded videos
- **Settings** - Configure backup options
- **Logs** - View real-time backup logs

You can trigger manual backups from the web interface at any time.

## Output Structure

```
/data/rumble_backups/
└── ChannelName/
    ├── backup_report.json
    └── video_id/
        ├── video_id.mp4          # Video file
        ├── video_id.info.json    # Full yt-dlp metadata
        ├── video_id.jpg          # Thumbnail
        ├── video_id.en.vtt       # Subtitles (if available)
        └── metadata.json         # Simplified metadata
```

### Metadata Example

```json
{
  "id": "v5abc123",
  "title": "Video Title",
  "description": "Video description...",
  "duration": 1234,
  "view_count": 50000,
  "like_count": 2500,
  "upload_date": "20240115",
  "uploader": "ChannelName",
  "channel": "ChannelName",
  "thumbnail": "https://...",
  "webpage_url": "https://rumble.com/v5abc123-video.html"
}
```

## Building

```bash
docker build -t rumble-scraper .
```

## Logs

```bash
# Container logs
docker logs rumble-scraper

# Application logs
docker exec rumble-scraper cat /config/logs/rumble_scraper.log
```

## Troubleshooting

### 403 Forbidden Errors

This is IP-based Cloudflare blocking:
- Deploy to your Unraid server (different IP)
- Use a VPN
- Set `BROWSER_COOKIES=chrome` and visit Rumble in Chrome first
- Check [yt-dlp FAQ](https://github.com/yt-dlp/yt-dlp/wiki/FAQ)

### No Videos Found

- Verify channel name/URL is correct
- Test the URL in your browser
- Run with `LOG_LEVEL=DEBUG`

### Cookie Issues

1. Visit rumble.com in your browser
2. Browse a few pages
3. Run the backup within 30 minutes
4. Try different browser: `BROWSER_COOKIES=firefox`

## How It Works

1. Uses [yt-dlp](https://github.com/yt-dlp/yt-dlp) with `--impersonate chrome` flag
2. Requires [curl_cffi](https://pypi.org/project/curl-cffi/) library for TLS fingerprinting
3. Optionally extracts cookies from your browser session
4. Downloads videos and metadata to organized folders
5. Tracks downloaded videos to avoid re-downloading

## License

MIT - Use responsibly. Respect Rumble's Terms of Service.
