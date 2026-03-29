"""
Screen recording helpers for Delimit MCP.

Two modes:
- browser: Xvfb + Chromium + ffmpeg -> MP4
- terminal: asciinema + agg + ffmpeg -> .cast + GIF + MP4

Bonus:
- take_screenshot: Chromium headless screenshot -> PNG
"""

import logging
import os
import shutil
import signal
import subprocess
import time
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger("delimit.ai.screen_record")

# ── Constants ────────────────────────────────────────────────────────────

CHROMIUM_PATH = "/root/.cache/puppeteer/chrome/linux-146.0.7680.153/chrome-linux64/chrome"
CONTENT_BASE = Path.home() / ".delimit" / "content"
VIDEOS_DIR = CONTENT_BASE / "videos"
GIFS_DIR = CONTENT_BASE / "gifs"
CASTS_DIR = CONTENT_BASE / "casts"
SCREENSHOTS_DIR = CONTENT_BASE / "screenshots"

MAX_DURATION = 120
DEFAULT_WIDTH = 1920
DEFAULT_HEIGHT = 1080
DISPLAY_NUM = 99


def _ensure_dirs():
    """Create output directories if they don't exist."""
    for d in (VIDEOS_DIR, GIFS_DIR, CASTS_DIR, SCREENSHOTS_DIR):
        d.mkdir(parents=True, exist_ok=True)


def _check_binary(name: str) -> Optional[str]:
    """Return path to binary or None if not found."""
    return shutil.which(name)


def _file_size_kb(path: Path) -> int:
    """Return file size in KB, or 0 if missing."""
    try:
        return int(path.stat().st_size / 1024)
    except (OSError, FileNotFoundError):
        return 0


def _kill_pid(pid: int):
    """Kill a process, ignoring errors."""
    try:
        os.kill(pid, signal.SIGTERM)
    except (OSError, ProcessLookupError):
        pass


# ── Browser Recording ────────────────────────────────────────────────────

def record_browser(url: str, name: str, duration: int) -> Dict[str, Any]:
    """Record a Chromium browser session visiting a URL as 1080p MP4.

    Starts Xvfb virtual display, ffmpeg screen capture, and Chromium.
    Cleans up all processes on completion or failure.
    """
    # Dependency checks
    missing = []
    if not _check_binary("Xvfb"):
        missing.append("Xvfb (apt install xvfb)")
    if not _check_binary("ffmpeg"):
        missing.append("ffmpeg (apt install ffmpeg)")
    if not Path(CHROMIUM_PATH).exists():
        missing.append(f"Chromium at {CHROMIUM_PATH}")
    if missing:
        return {
            "recorded": False,
            "error": "missing_dependencies",
            "message": f"Required binaries not found: {', '.join(missing)}",
        }

    if not url:
        return {"recorded": False, "error": "missing_url", "message": "url is required for browser mode"}

    duration = min(max(1, duration), MAX_DURATION)
    _ensure_dirs()

    output_path = VIDEOS_DIR / f"{name}.mp4"
    display = f":{DISPLAY_NUM}"

    xvfb_proc = None
    ffmpeg_proc = None
    chrome_proc = None

    try:
        # 1. Start virtual display
        xvfb_proc = subprocess.Popen(
            ["Xvfb", display, "-screen", "0", f"{DEFAULT_WIDTH}x{DEFAULT_HEIGHT}x24"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        time.sleep(1)

        env = os.environ.copy()
        env["DISPLAY"] = display

        # 2. Start ffmpeg recording
        ffmpeg_proc = subprocess.Popen(
            [
                "ffmpeg", "-y",
                "-video_size", f"{DEFAULT_WIDTH}x{DEFAULT_HEIGHT}",
                "-framerate", "30",
                "-f", "x11grab", "-i", display,
                "-t", str(duration),
                "-c:v", "libx264", "-preset", "ultrafast", "-crf", "23",
                "-pix_fmt", "yuv420p",
                str(output_path),
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            env=env,
        )
        time.sleep(1)

        # 3. Launch Chromium
        chrome_proc = subprocess.Popen(
            [
                CHROMIUM_PATH,
                "--no-sandbox",
                "--disable-gpu",
                "--disable-dev-shm-usage",
                f"--window-size={DEFAULT_WIDTH},{DEFAULT_HEIGHT}",
                "--start-maximized",
                url,
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            env=env,
        )

        # 4. Wait for ffmpeg to finish (it will stop after -t duration)
        ffmpeg_proc.wait(timeout=duration + 30)

        return {
            "recorded": True,
            "mode": "browser",
            "files": {
                "mp4": str(output_path),
            },
            "duration": duration,
            "size_kb": _file_size_kb(output_path),
            "url": url,
        }

    except subprocess.TimeoutExpired:
        if ffmpeg_proc:
            ffmpeg_proc.kill()
        return {
            "recorded": False,
            "error": "timeout",
            "message": f"Recording timed out after {duration + 30}s",
        }
    except Exception as e:
        logger.error("Browser recording failed: %s", e)
        return {
            "recorded": False,
            "error": "recording_failed",
            "message": str(e),
        }
    finally:
        # Always clean up processes
        if chrome_proc and chrome_proc.poll() is None:
            _kill_pid(chrome_proc.pid)
        if ffmpeg_proc and ffmpeg_proc.poll() is None:
            _kill_pid(ffmpeg_proc.pid)
        if xvfb_proc and xvfb_proc.poll() is None:
            _kill_pid(xvfb_proc.pid)


# ── Terminal Recording ───────────────────────────────────────────────────

def record_terminal(name: str, duration: int, script: str = "") -> Dict[str, Any]:
    """Record a terminal session as .cast + GIF + MP4.

    Uses asciinema to record, agg to convert to GIF, ffmpeg for MP4.
    If script is provided, it runs non-interactively via asciinema rec -c.
    """
    missing = []
    if not _check_binary("asciinema"):
        missing.append("asciinema (pip install asciinema)")
    if not _check_binary("agg"):
        missing.append("agg (cargo install agg)")
    if not _check_binary("ffmpeg"):
        missing.append("ffmpeg (apt install ffmpeg)")
    if missing:
        return {
            "recorded": False,
            "error": "missing_dependencies",
            "message": f"Required binaries not found: {', '.join(missing)}",
        }

    duration = min(max(1, duration), MAX_DURATION)
    _ensure_dirs()

    cast_path = CASTS_DIR / f"{name}.cast"
    gif_path = GIFS_DIR / f"{name}.gif"
    mp4_path = VIDEOS_DIR / f"{name}.mp4"

    try:
        # 1. Record with asciinema
        asciinema_cmd = [
            "asciinema", "rec", str(cast_path),
            "--overwrite", "--cols", "120", "--rows", "35",
        ]

        if script:
            # Run a command non-interactively
            asciinema_cmd.extend(["-c", script])
            result = subprocess.run(
                asciinema_cmd,
                timeout=duration + 10,
                capture_output=True,
                text=True,
            )
        else:
            # Record idle terminal for specified duration
            # Use a simple sleep command to fill the duration
            asciinema_cmd.extend(["-c", f"sleep {duration}"])
            result = subprocess.run(
                asciinema_cmd,
                timeout=duration + 10,
                capture_output=True,
                text=True,
            )

        if not cast_path.exists():
            return {
                "recorded": False,
                "error": "asciinema_failed",
                "message": f"asciinema did not produce output: {result.stderr}",
            }

        files = {"cast": str(cast_path)}

        # 2. Convert to GIF via agg
        agg_result = subprocess.run(
            [
                "agg", str(cast_path), str(gif_path),
                "--font-size", "16",
                "--theme", "monokai",
                "--speed", "1.5",
                "--cols", "120",
                "--rows", "35",
            ],
            timeout=60,
            capture_output=True,
            text=True,
        )
        if gif_path.exists():
            files["gif"] = str(gif_path)

        # 3. Convert GIF to MP4 via ffmpeg
        if gif_path.exists():
            ffmpeg_result = subprocess.run(
                [
                    "ffmpeg", "-y", "-i", str(gif_path),
                    "-movflags", "faststart",
                    "-pix_fmt", "yuv420p",
                    "-vf", "scale=trunc(iw/2)*2:trunc(ih/2)*2",
                    str(mp4_path),
                ],
                timeout=60,
                capture_output=True,
                text=True,
            )
            if mp4_path.exists():
                files["mp4"] = str(mp4_path)

        return {
            "recorded": True,
            "mode": "terminal",
            "files": files,
            "duration": duration,
            "size_kb": _file_size_kb(mp4_path) or _file_size_kb(gif_path) or _file_size_kb(cast_path),
        }

    except subprocess.TimeoutExpired:
        return {
            "recorded": False,
            "error": "timeout",
            "message": f"Terminal recording timed out after {duration + 10}s",
        }
    except Exception as e:
        logger.error("Terminal recording failed: %s", e)
        return {
            "recorded": False,
            "error": "recording_failed",
            "message": str(e),
        }


# ── Screenshot ───────────────────────────────────────────────────────────

def take_screenshot(url: str, name: str) -> Dict[str, Any]:
    """Take a single screenshot of a URL using headless Chromium.

    Returns PNG path. Useful for audit evidence and visual regression.
    """
    if not Path(CHROMIUM_PATH).exists():
        return {
            "recorded": False,
            "error": "missing_dependencies",
            "message": f"Chromium not found at {CHROMIUM_PATH}",
        }

    if not url:
        return {"recorded": False, "error": "missing_url", "message": "url is required for screenshot"}

    _ensure_dirs()
    output_path = SCREENSHOTS_DIR / f"{name}.png"

    try:
        result = subprocess.run(
            [
                CHROMIUM_PATH,
                "--headless",
                "--no-sandbox",
                "--disable-gpu",
                "--disable-dev-shm-usage",
                f"--window-size={DEFAULT_WIDTH},{DEFAULT_HEIGHT}",
                f"--screenshot={output_path}",
                url,
            ],
            timeout=30,
            capture_output=True,
            text=True,
        )

        if output_path.exists():
            return {
                "recorded": True,
                "mode": "screenshot",
                "files": {
                    "png": str(output_path),
                },
                "size_kb": _file_size_kb(output_path),
                "url": url,
            }
        else:
            return {
                "recorded": False,
                "error": "screenshot_failed",
                "message": f"Chromium did not produce screenshot: {result.stderr[:500]}",
            }

    except subprocess.TimeoutExpired:
        return {
            "recorded": False,
            "error": "timeout",
            "message": "Screenshot timed out after 30s",
        }
    except Exception as e:
        logger.error("Screenshot failed: %s", e)
        return {
            "recorded": False,
            "error": "screenshot_failed",
            "message": str(e),
        }
