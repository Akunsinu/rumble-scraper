#!/usr/bin/env python3
"""
Rumble Channel Backup Script
============================
Downloads videos from Rumble channels with metadata.

This script uses a two-phase approach:
1. Scrape channel page to get video IDs
2. Download each video using embed URLs (which bypass Cloudflare)
"""

import os
import sys
import json
import time
import logging
import re
import random
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, List, Any

import yt_dlp

# =============================================================================
# Configuration
# =============================================================================

RUMBLE_BASE_URL = "https://rumble.com"
RUMBLE_EMBED_URL = "https://rumble.com/embed"
DEFAULT_OUTPUT_DIR = "/data/rumble_backups"
DEFAULT_CONFIG_DIR = "/config"

LOG_FORMAT = "%(asctime)s - %(levelname)s - %(message)s"
LOG_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

# =============================================================================
# Logging
# =============================================================================

def setup_logging(log_level: str = "INFO") -> logging.Logger:
    """Configure logging."""
    logger = logging.getLogger("rumble_scraper")
    logger.setLevel(getattr(logging, log_level.upper(), logging.INFO))

    # Clear existing handlers to avoid duplicates
    logger.handlers = []

    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(logging.Formatter(LOG_FORMAT, LOG_DATE_FORMAT))
    logger.addHandler(console_handler)

    log_dir = Path(os.environ.get("LOG_DIR", "/config/logs"))
    if log_dir.exists() or log_dir.parent.exists():
        log_dir.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(log_dir / "rumble_scraper.log")
        file_handler.setFormatter(logging.Formatter(LOG_FORMAT, LOG_DATE_FORMAT))
        logger.addHandler(file_handler)

    return logger


# =============================================================================
# Channel URL Handling
# =============================================================================

def get_channel_url(channel_identifier: str) -> str:
    """Convert channel identifier to full URL."""
    if channel_identifier.startswith("http"):
        return channel_identifier

    channel_identifier = channel_identifier.lstrip("/")

    if channel_identifier.startswith("c/"):
        return f"{RUMBLE_BASE_URL}/{channel_identifier}"
    elif channel_identifier.startswith("user/"):
        return f"{RUMBLE_BASE_URL}/{channel_identifier}"
    else:
        return f"{RUMBLE_BASE_URL}/c/{channel_identifier}"


def get_embed_url(video_id: str) -> str:
    """Convert video ID to embed URL (bypasses Cloudflare)."""
    video_id = video_id.strip()
    # Ensure ID starts with 'v'
    if not video_id.startswith("v"):
        video_id = f"v{video_id}"
    return f"{RUMBLE_EMBED_URL}/{video_id}"


# =============================================================================
# yt-dlp Options
# =============================================================================

def get_ydl_opts(
    output_dir: Optional[Path] = None,
    cookies_file: Optional[str] = None,
    download: bool = True,
    quiet: bool = False
) -> dict:
    """Get yt-dlp options for downloading."""
    opts = {
        # Format selection - best quality
        "format": "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best",
        "merge_output_format": "mp4",

        # Download settings
        "ignoreerrors": False,
        "no_warnings": quiet,
        "quiet": quiet,

        # Metadata
        "writeinfojson": True,
        "writethumbnail": True,
        "writesubtitles": True,
        "writeautomaticsub": True,
        "subtitleslangs": ["en"],

        # Network - robust settings
        "socket_timeout": 60,
        "retries": 10,
        "fragment_retries": 10,

        # Rate limiting
        "sleep_interval": random.randint(1, 3),
        "max_sleep_interval": random.randint(4, 6),
    }

    if output_dir:
        opts["outtmpl"] = "%(id)s.%(ext)s"
        opts["paths"] = {"home": str(output_dir)}

    if cookies_file and Path(cookies_file).exists():
        opts["cookiefile"] = cookies_file

    if not download:
        opts["skip_download"] = True
        opts["writethumbnail"] = False
        opts["writeinfojson"] = False

    return opts


# =============================================================================
# Video Scraping - Get list of videos from channel
# =============================================================================

def scrape_channel_videos(
    channel_url: str,
    logger: logging.Logger,
    max_videos: Optional[int] = None
) -> List[Dict[str, Any]]:
    """
    Scrape video list from a Rumble channel.
    """
    videos = []
    logger.info(f"Scraping channel: {channel_url}")

    opts = {
        "quiet": True,
        "no_warnings": True,
        "extract_flat": True,
        "ignoreerrors": True,
    }

    if max_videos:
        opts["playlistend"] = max_videos

    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            result = ydl.extract_info(channel_url, download=False)

            if result is None:
                logger.warning("No results returned from channel")
                return videos

            entries = result.get("entries", [])
            if not entries and result.get("id"):
                entries = [result]

            for entry in entries:
                if entry is None:
                    continue

                video_id = entry.get("id", "")
                if not video_id:
                    continue

                # Construct embed URL for downloading
                embed_url = get_embed_url(video_id)

                videos.append({
                    "id": video_id,
                    "url": entry.get("webpage_url") or entry.get("url") or embed_url,
                    "embed_url": embed_url,
                    "title": entry.get("title", video_id),
                })

            logger.info(f"Found {len(videos)} videos")

    except yt_dlp.utils.DownloadError as e:
        error_msg = str(e)
        if "403" in error_msg:
            logger.error("403 Forbidden - Channel page blocked by Cloudflare")
            logger.error("Your IP may be blocked. Try from a different network.")
        else:
            logger.error(f"Failed to scrape channel: {e}")
    except Exception as e:
        logger.error(f"Failed to scrape channel: {e}")

    return videos


# =============================================================================
# Video Download - Download individual video using embed URL
# =============================================================================

def download_video(
    video_id: str,
    output_dir: Path,
    logger: logging.Logger,
    cookies_file: Optional[str] = None
) -> Dict[str, Any]:
    """
    Download a video using its embed URL (bypasses Cloudflare).
    """
    result = {
        "success": False,
        "video_file": None,
        "metadata": None,
        "error": None
    }

    output_dir.mkdir(parents=True, exist_ok=True)

    # Always use embed URL (bypasses Cloudflare)
    embed_url = get_embed_url(video_id)

    opts = get_ydl_opts(
        output_dir=output_dir,
        cookies_file=cookies_file,
        download=True
    )

    try:
        logger.info(f"Downloading: {video_id} from {embed_url}")

        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(embed_url, download=True)

            if info:
                # The actual video ID from yt-dlp may differ from what we passed
                actual_id = info.get("id", video_id)

                # Find the downloaded video file
                video_file = None
                for check_id in [actual_id, video_id, f"v{video_id}", video_id.lstrip("v")]:
                    for ext in ["mp4", "webm", "mkv"]:
                        potential_file = output_dir / f"{check_id}.{ext}"
                        if potential_file.exists():
                            video_file = potential_file
                            break
                    if video_file:
                        break

                if video_file and video_file.exists():
                    result["success"] = True
                    result["video_file"] = str(video_file)
                    result["metadata"] = {
                        "id": actual_id,
                        "title": info.get("title"),
                        "description": info.get("description"),
                        "duration": info.get("duration"),
                        "view_count": info.get("view_count"),
                        "like_count": info.get("like_count"),
                        "upload_date": info.get("upload_date"),
                        "uploader": info.get("uploader"),
                        "channel": info.get("channel"),
                        "thumbnail": info.get("thumbnail"),
                        "webpage_url": info.get("webpage_url"),
                    }
                    logger.info(f"Downloaded: {info.get('title', video_id)}")
                else:
                    result["error"] = "Video file not found after download"
                    logger.error(f"Download completed but file not found for {video_id}")
            else:
                result["error"] = "No info returned from yt-dlp"
                logger.error(f"No info returned for {video_id}")

    except yt_dlp.utils.DownloadError as e:
        result["error"] = str(e)
        logger.error(f"Download failed for {video_id}: {e}")
    except Exception as e:
        result["error"] = str(e)
        logger.error(f"Unexpected error downloading {video_id}: {e}")

    return result


# =============================================================================
# Backup State Management
# =============================================================================

def load_backup_state(config_dir: Path) -> Dict[str, Any]:
    """Load backup state from disk."""
    state_file = config_dir / "backup_state.json"
    if state_file.exists():
        try:
            with open(state_file, "r") as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            pass
    return {"channels": {}, "last_run": None}


def save_backup_state(config_dir: Path, state: Dict[str, Any]) -> None:
    """Save backup state to disk."""
    state_file = config_dir / "backup_state.json"
    config_dir.mkdir(parents=True, exist_ok=True)
    with open(state_file, "w") as f:
        json.dump(state, f, indent=2)


def is_video_downloaded(channel_output_dir: Path, video_id: str) -> bool:
    """Check if a video file actually exists on disk."""
    video_dir = channel_output_dir / video_id
    if not video_dir.exists():
        return False

    # Check various ID formats
    ids_to_check = [video_id, f"v{video_id}", video_id.lstrip("v")]

    for check_id in ids_to_check:
        for ext in ["mp4", "webm", "mkv"]:
            if (video_dir / f"{check_id}.{ext}").exists():
                return True

    return False


# =============================================================================
# Main Backup Function
# =============================================================================

def backup_channel(
    channel_identifier: str,
    output_dir: Path,
    config_dir: Path,
    logger: logging.Logger,
    cookies_file: Optional[str] = None,
    force_rescan: bool = False,
    max_videos: Optional[int] = None
) -> Dict[str, Any]:
    """Backup a Rumble channel."""
    stats = {
        "channel": channel_identifier,
        "videos_found": 0,
        "videos_downloaded": 0,
        "videos_skipped": 0,
        "videos_failed": 0,
        "started_at": datetime.now().isoformat(),
        "completed_at": None,
        "errors": []
    }

    channel_url = get_channel_url(channel_identifier)
    logger.info(f"Backing up channel: {channel_url}")

    # Create channel output directory
    safe_name = re.sub(r"[^\w\-]", "_", channel_identifier)
    channel_output_dir = output_dir / safe_name
    channel_output_dir.mkdir(parents=True, exist_ok=True)

    # Load state
    state = load_backup_state(config_dir)
    channel_state = state["channels"].get(channel_identifier, {"downloaded_videos": []})
    downloaded_videos = set(channel_state.get("downloaded_videos", []))

    # Get video list
    videos = scrape_channel_videos(channel_url, logger, max_videos=max_videos)
    stats["videos_found"] = len(videos)

    if not videos:
        logger.warning("No videos found!")
        return stats

    # Process videos
    for i, video_info in enumerate(videos, 1):
        video_id = video_info.get("id", "")

        if not video_id:
            logger.warning(f"Skipping video {i} - no video ID")
            continue

        logger.info(f"Processing video {i}/{len(videos)}: {video_id}")

        # Check if already downloaded
        if not force_rescan:
            if video_id in downloaded_videos and is_video_downloaded(channel_output_dir, video_id):
                logger.info(f"Skipping already downloaded: {video_id}")
                stats["videos_skipped"] += 1
                continue
            elif video_id in downloaded_videos:
                logger.info(f"Re-downloading {video_id} (file missing)")
                downloaded_videos.discard(video_id)

        # Create video directory
        video_output_dir = channel_output_dir / video_id
        video_output_dir.mkdir(parents=True, exist_ok=True)

        # Download using embed URL
        result = download_video(
            video_id,
            video_output_dir,
            logger,
            cookies_file=cookies_file
        )

        if result["success"] and result["video_file"]:
            if Path(result["video_file"]).exists():
                stats["videos_downloaded"] += 1
                downloaded_videos.add(video_id)

                # Save metadata
                if result["metadata"]:
                    metadata_file = video_output_dir / "metadata.json"
                    with open(metadata_file, "w", encoding="utf-8") as f:
                        json.dump(result["metadata"], f, indent=2, ensure_ascii=False)

                # Save state after each successful download
                channel_state["downloaded_videos"] = list(downloaded_videos)
                channel_state["last_backup"] = datetime.now().isoformat()
                state["channels"][channel_identifier] = channel_state
                state["last_run"] = datetime.now().isoformat()
                save_backup_state(config_dir, state)
            else:
                stats["videos_failed"] += 1
                stats["errors"].append(f"{video_id}: File not found")
        else:
            stats["videos_failed"] += 1
            stats["errors"].append(f"{video_id}: {result.get('error', 'Unknown error')}")

        # Rate limiting
        time.sleep(random.uniform(2, 5))

    stats["completed_at"] = datetime.now().isoformat()

    # Save report
    report_file = channel_output_dir / "backup_report.json"
    with open(report_file, "w") as f:
        json.dump(stats, f, indent=2)

    logger.info(f"Backup completed. Downloaded: {stats['videos_downloaded']}, "
                f"Skipped: {stats['videos_skipped']}, Failed: {stats['videos_failed']}")

    return stats


# =============================================================================
# Configuration
# =============================================================================

def load_config(config_path: Path) -> Dict[str, Any]:
    """Load configuration from file."""
    default_config = {
        "channels": [],
        "output_dir": DEFAULT_OUTPUT_DIR,
        "log_level": "INFO",
        "max_videos_per_channel": None,
        "force_rescan": False,
        "cookies_file": None,
    }

    if not config_path.exists():
        return default_config

    try:
        with open(config_path, "r") as f:
            user_config = json.load(f)
        default_config.update(user_config or {})
    except (json.JSONDecodeError, IOError) as e:
        print(f"Warning: Failed to load config: {e}")

    return default_config


# =============================================================================
# Main
# =============================================================================

def main():
    """Main entry point."""
    config_dir = Path(os.environ.get("CONFIG_DIR", DEFAULT_CONFIG_DIR))
    output_dir = Path(os.environ.get("OUTPUT_DIR", DEFAULT_OUTPUT_DIR))

    config_dir.mkdir(parents=True, exist_ok=True)
    output_dir.mkdir(parents=True, exist_ok=True)

    # Load config
    config_file = config_dir / "config.json"
    config = load_config(config_file)

    # Environment overrides
    if os.environ.get("CHANNELS"):
        config["channels"] = [c.strip() for c in os.environ["CHANNELS"].split(",") if c.strip()]
    if os.environ.get("LOG_LEVEL"):
        config["log_level"] = os.environ["LOG_LEVEL"]
    if os.environ.get("MAX_VIDEOS"):
        config["max_videos_per_channel"] = int(os.environ["MAX_VIDEOS"])
    if os.environ.get("FORCE_RESCAN"):
        config["force_rescan"] = os.environ["FORCE_RESCAN"].lower() in ("true", "1", "yes")
    if os.environ.get("COOKIES_FILE"):
        config["cookies_file"] = os.environ["COOKIES_FILE"]

    # Setup logging
    logger = setup_logging(config.get("log_level", "INFO"))

    logger.info("=" * 60)
    logger.info("Rumble Channel Backup Script")
    logger.info("=" * 60)
    logger.info(f"Config directory: {config_dir}")
    logger.info(f"Output directory: {output_dir}")
    logger.info(f"Channels: {config.get('channels', [])}")

    # Check channels
    channels = list(dict.fromkeys(config.get("channels", [])))  # Dedupe
    if not channels:
        logger.warning("No channels configured!")
        logger.info("Set CHANNELS env var or add to config.json")
        return

    # Backup each channel
    all_stats = []
    for channel in channels:
        if not channel:
            continue

        logger.info(f"\n{'='*60}")
        logger.info(f"Backing up: {channel}")
        logger.info(f"{'='*60}")

        try:
            stats = backup_channel(
                channel_identifier=channel,
                output_dir=output_dir,
                config_dir=config_dir,
                logger=logger,
                cookies_file=config.get("cookies_file"),
                force_rescan=config.get("force_rescan", False),
                max_videos=config.get("max_videos_per_channel")
            )
            all_stats.append(stats)

        except Exception as e:
            logger.error(f"Failed to backup {channel}: {e}")
            all_stats.append({
                "channel": channel,
                "error": str(e),
                "videos_downloaded": 0,
                "videos_failed": 0
            })

    # Summary
    logger.info("\n" + "=" * 60)
    logger.info("BACKUP SUMMARY")
    logger.info("=" * 60)

    total_downloaded = 0
    total_failed = 0

    for stats in all_stats:
        channel = stats.get("channel", "Unknown")
        found = stats.get("videos_found", 0)
        downloaded = stats.get("videos_downloaded", 0)
        failed = stats.get("videos_failed", 0)
        skipped = stats.get("videos_skipped", 0)

        logger.info(f"\n{channel}:")
        logger.info(f"  Found: {found}")
        logger.info(f"  Downloaded: {downloaded}")
        logger.info(f"  Skipped: {skipped}")
        logger.info(f"  Failed: {failed}")

        total_downloaded += downloaded
        total_failed += failed

    logger.info(f"\nTotal downloaded: {total_downloaded}")
    logger.info(f"Total failed: {total_failed}")
    logger.info("Backup complete!")


if __name__ == "__main__":
    main()
