#!/usr/bin/env python3
"""
Rumble Channel Backup Script
============================
Downloads videos from Rumble channels with metadata.

Due to Cloudflare protection, this script requires:
1. Browser cookies exported from a recent Rumble session
2. The --impersonate chrome flag with curl_cffi installed

Install: pip install "yt-dlp[curl_cffi]"
"""

import os
import sys
import json
import time
import logging
import re
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, List, Any
from dataclasses import dataclass, asdict

import random
import yt_dlp
from yt_dlp.networking.impersonate import ImpersonateTarget

# Browser versions to rotate through for better evasion
CHROME_VERSIONS = ["chrome", "chrome-120", "chrome-131", "chrome-133"]

# =============================================================================
# Configuration
# =============================================================================

RUMBLE_BASE_URL = "https://rumble.com"
DEFAULT_OUTPUT_DIR = "/data/rumble_backups"
DEFAULT_CONFIG_DIR = "/config"

LOG_FORMAT = "%(asctime)s - %(levelname)s - %(message)s"
LOG_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

# =============================================================================
# Data Classes
# =============================================================================

@dataclass
class VideoMetadata:
    """Stores metadata for a video."""
    video_id: str
    title: str
    url: str
    channel_name: str
    channel_url: Optional[str] = None
    upload_date: Optional[str] = None
    duration: Optional[int] = None
    views: Optional[int] = None
    likes: Optional[int] = None
    description: Optional[str] = None
    thumbnail_url: Optional[str] = None
    scraped_at: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# =============================================================================
# Logging
# =============================================================================

def setup_logging(log_level: str = "INFO") -> logging.Logger:
    """Configure logging."""
    logger = logging.getLogger("rumble_scraper")
    logger.setLevel(getattr(logging, log_level.upper(), logging.INFO))

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


# =============================================================================
# yt-dlp Based Functions (with Cloudflare bypass)
# =============================================================================

def get_ydl_opts(
    output_dir: Optional[Path] = None,
    cookies_file: Optional[str] = None,
    browser_cookies: Optional[str] = None,
    download: bool = True
) -> dict:
    """
    Get yt-dlp options configured for Rumble with Cloudflare bypass.

    Args:
        output_dir: Directory to save files
        cookies_file: Path to cookies.txt file
        browser_cookies: Browser name for --cookies-from-browser (chrome, firefox, etc.)
        download: Whether to download or just extract info
    """
    # Randomize browser version for better evasion
    browser_version = random.choice(CHROME_VERSIONS)

    opts = {
        # Impersonate Chrome to bypass Cloudflare
        # Use ImpersonateTarget for proper format, rotate versions
        "impersonate": ImpersonateTarget(browser_version),

        # Format selection - best quality
        "format": "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best",
        "merge_output_format": "mp4",

        # Download settings
        "ignoreerrors": True,
        "no_warnings": False,
        "quiet": False,

        # Metadata
        "writeinfojson": True,
        "writethumbnail": True,
        "writesubtitles": True,
        "writeautomaticsub": True,
        "subtitleslangs": ["en"],

        # Network - increased timeouts and retries
        "socket_timeout": 60,
        "retries": 10,
        "fragment_retries": 10,

        # Rate limiting - randomized to appear more human-like
        "sleep_interval": random.randint(2, 4),
        "max_sleep_interval": random.randint(5, 8),

        # HTTP headers to match browser
        "http_headers": {
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
            "Accept-Encoding": "gzip, deflate, br",
            "DNT": "1",
            "Connection": "keep-alive",
            "Upgrade-Insecure-Requests": "1",
            "Sec-Fetch-Dest": "document",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": "none",
            "Sec-Fetch-User": "?1",
            "Cache-Control": "max-age=0",
        },
    }

    if output_dir:
        # Use relative path in template, set home path separately
        opts["outtmpl"] = "%(id)s.%(ext)s"
        opts["paths"] = {"home": str(output_dir)}

    if cookies_file and Path(cookies_file).exists():
        opts["cookiefile"] = cookies_file

    # Only use browser cookies if we're not in Docker (browser won't exist in container)
    if browser_cookies:
        # Check if we're likely in Docker by looking for common browser paths
        import platform
        in_docker = Path("/.dockerenv").exists() or platform.system() == "Linux"

        if not in_docker:
            opts["cookiesfrombrowser"] = (browser_cookies,)
        # In Docker, skip browser cookies - they won't exist

    if not download:
        opts["skip_download"] = True
        opts["writethumbnail"] = False

    return opts


def scrape_channel_videos(
    channel_url: str,
    logger: logging.Logger,
    cookies_file: Optional[str] = None,
    browser_cookies: Optional[str] = None,
    max_videos: Optional[int] = None
) -> List[Dict[str, Any]]:
    """
    Scrape video list from a Rumble channel using yt-dlp.

    Args:
        channel_url: URL of the channel
        logger: Logger instance
        cookies_file: Path to cookies file
        browser_cookies: Browser to extract cookies from
        max_videos: Maximum number of videos to return

    Returns:
        List of video info dictionaries
    """
    videos = []
    logger.info(f"Scraping channel: {channel_url}")

    opts = get_ydl_opts(
        cookies_file=cookies_file,
        browser_cookies=browser_cookies,
        download=False
    )
    opts["extract_flat"] = "in_playlist"
    opts["playlistend"] = max_videos if max_videos else None

    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            result = ydl.extract_info(channel_url, download=False)

            if result is None:
                logger.warning("No results returned from channel")
                return videos

            # Handle playlist/channel results
            entries = result.get("entries", [])
            if not entries and result.get("id"):
                entries = [result]

            for entry in entries:
                if entry is None:
                    continue

                videos.append({
                    "id": entry.get("id", ""),
                    "url": entry.get("url") or entry.get("webpage_url", ""),
                    "title": entry.get("title", ""),
                })

            logger.info(f"Found {len(videos)} videos")

    except yt_dlp.utils.DownloadError as e:
        error_msg = str(e)
        if "403" in error_msg:
            logger.error(f"403 Forbidden - Your IP is blocked by Cloudflare")
            logger.error(f"Solutions:")
            logger.error(f"  1. Try from a different IP (deploy to Unraid)")
            logger.error(f"  2. Set BROWSER_COOKIES=chrome and visit Rumble in Chrome first")
            logger.error(f"  3. Use a VPN with a residential IP")
        else:
            logger.error(f"Failed to scrape channel: {e}")
    except Exception as e:
        logger.error(f"Failed to scrape channel: {e}")

    return videos


def download_video(
    video_url: str,
    output_dir: Path,
    logger: logging.Logger,
    cookies_file: Optional[str] = None,
    browser_cookies: Optional[str] = None
) -> Dict[str, Any]:
    """
    Download a video using yt-dlp with Cloudflare bypass.

    Args:
        video_url: URL of the video
        output_dir: Directory to save files
        logger: Logger instance
        cookies_file: Path to cookies file
        browser_cookies: Browser to extract cookies from

    Returns:
        Dictionary with download results
    """
    result = {
        "success": False,
        "video_file": None,
        "metadata": None,
        "error": None
    }

    output_dir.mkdir(parents=True, exist_ok=True)

    opts = get_ydl_opts(
        output_dir=output_dir,
        cookies_file=cookies_file,
        browser_cookies=browser_cookies,
        download=True
    )

    try:
        logger.info(f"Downloading: {video_url}")

        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(video_url, download=True)

            if info:
                result["success"] = True
                result["metadata"] = {
                    "id": info.get("id"),
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

                # Find downloaded file
                video_id = info.get("id", "")
                for ext in ["mp4", "webm", "mkv"]:
                    video_file = output_dir / f"{video_id}.{ext}"
                    if video_file.exists():
                        result["video_file"] = str(video_file)
                        break

                logger.info(f"Downloaded: {info.get('title', video_url)}")

    except yt_dlp.utils.DownloadError as e:
        result["error"] = str(e)
        logger.error(f"Download failed: {e}")
    except Exception as e:
        result["error"] = str(e)
        logger.error(f"Unexpected error: {e}")

    return result


# =============================================================================
# Backup Management
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


def backup_channel(
    channel_identifier: str,
    output_dir: Path,
    config_dir: Path,
    logger: logging.Logger,
    cookies_file: Optional[str] = None,
    browser_cookies: Optional[str] = None,
    force_rescan: bool = False,
    max_videos: Optional[int] = None
) -> Dict[str, Any]:
    """
    Backup a Rumble channel.

    Args:
        channel_identifier: Channel URL or name
        output_dir: Base output directory
        config_dir: Configuration directory
        logger: Logger instance
        cookies_file: Path to cookies file
        browser_cookies: Browser to extract cookies from
        force_rescan: Re-download all videos
        max_videos: Maximum videos to process

    Returns:
        Backup statistics
    """
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
    videos = scrape_channel_videos(
        channel_url,
        logger,
        cookies_file=cookies_file,
        browser_cookies=browser_cookies,
        max_videos=max_videos
    )
    stats["videos_found"] = len(videos)

    if not videos:
        logger.warning("No videos found. This may be due to Cloudflare blocking.")
        logger.info("Try: 1) Export cookies from browser, 2) Use --browser-cookies option")
        return stats

    # Process videos
    for i, video_info in enumerate(videos, 1):
        video_id = video_info.get("id", "")
        video_url = video_info.get("url", "")

        if not video_url:
            continue

        logger.info(f"Processing video {i}/{len(videos)}: {video_id}")

        # Skip if already downloaded
        if video_id in downloaded_videos and not force_rescan:
            logger.info(f"Skipping already downloaded: {video_id}")
            stats["videos_skipped"] += 1
            continue

        # Create video directory
        video_output_dir = channel_output_dir / video_id
        video_output_dir.mkdir(parents=True, exist_ok=True)

        # Download
        result = download_video(
            video_url,
            video_output_dir,
            logger,
            cookies_file=cookies_file,
            browser_cookies=browser_cookies
        )

        if result["success"]:
            stats["videos_downloaded"] += 1
            downloaded_videos.add(video_id)

            # Save metadata
            if result["metadata"]:
                metadata_file = video_output_dir / "metadata.json"
                with open(metadata_file, "w", encoding="utf-8") as f:
                    json.dump(result["metadata"], f, indent=2, ensure_ascii=False)
        else:
            stats["videos_failed"] += 1
            stats["errors"].append(f"{video_id}: {result.get('error', 'Unknown error')}")

        # Rate limiting
        time.sleep(2)

    # Save state
    channel_state["downloaded_videos"] = list(downloaded_videos)
    channel_state["last_backup"] = datetime.now().isoformat()
    state["channels"][channel_identifier] = channel_state
    state["last_run"] = datetime.now().isoformat()
    save_backup_state(config_dir, state)

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
        "browser_cookies": None,  # chrome, firefox, edge, etc.
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
        config["channels"] = os.environ["CHANNELS"].split(",")
    if os.environ.get("LOG_LEVEL"):
        config["log_level"] = os.environ["LOG_LEVEL"]
    if os.environ.get("MAX_VIDEOS"):
        config["max_videos_per_channel"] = int(os.environ["MAX_VIDEOS"])
    if os.environ.get("FORCE_RESCAN"):
        config["force_rescan"] = os.environ["FORCE_RESCAN"].lower() in ("true", "1", "yes")
    if os.environ.get("COOKIES_FILE"):
        config["cookies_file"] = os.environ["COOKIES_FILE"]
    if os.environ.get("BROWSER_COOKIES"):
        config["browser_cookies"] = os.environ["BROWSER_COOKIES"]

    # Setup logging
    logger = setup_logging(config.get("log_level", "INFO"))

    logger.info("=" * 60)
    logger.info("Rumble Channel Backup Script")
    logger.info("=" * 60)
    logger.info(f"Config directory: {config_dir}")
    logger.info(f"Output directory: {output_dir}")
    logger.info(f"Channels: {config.get('channels', [])}")

    if config.get("cookies_file"):
        logger.info(f"Using cookies file: {config['cookies_file']}")
    if config.get("browser_cookies"):
        logger.info(f"Using cookies from browser: {config['browser_cookies']}")

    # Check channels
    channels = config.get("channels", [])
    if not channels:
        logger.warning("No channels configured!")
        logger.info("Set CHANNELS env var or add to config.json")

        # Create example config
        if not config_file.exists():
            example = {
                "channels": ["example_channel"],
                "log_level": "INFO",
                "max_videos_per_channel": None,
                "force_rescan": False,
                "cookies_file": None,
                "browser_cookies": "chrome"  # Use Chrome cookies by default
            }
            with open(config_file, "w") as f:
                json.dump(example, f, indent=2)
            logger.info(f"Created example config at: {config_file}")
        return

    # Backup each channel
    all_stats = []
    for channel in channels:
        channel = channel.strip()
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
                browser_cookies=config.get("browser_cookies"),
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
        downloaded = stats.get("videos_downloaded", 0)
        failed = stats.get("videos_failed", 0)
        skipped = stats.get("videos_skipped", 0)

        logger.info(f"\n{channel}:")
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
