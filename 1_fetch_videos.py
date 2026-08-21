"""Step 1 — Fetch all video URLs and metadata from a YouTube channel via yt-dlp."""
import json
import os
from pathlib import Path

import yt_dlp
from dotenv import load_dotenv

load_dotenv()

CHANNEL_URL = os.getenv("YOUTUBE_CHANNEL_URL")
OUT_PATH = Path(__file__).parent / "data" / "videos.json"


def fetch_videos(channel_url: str) -> list[dict]:
    ydl_opts = {
        "extract_flat": True,
        "quiet": True,
        "skip_download": True,
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(channel_url, download=False)

    entries = info.get("entries", [])
    # Channel listings can nest entries under tabs (e.g. "Videos" tab).
    videos = []
    for entry in entries:
        if entry is None:
            continue
        if entry.get("_type") == "playlist" and "entries" in entry:
            videos.extend(e for e in entry["entries"] if e)
        else:
            videos.append(entry)

    results = []
    for v in videos:
        video_id = v.get("id")
        if not video_id:
            continue
        results.append(
            {
                "id": video_id,
                "url": v.get("url") or f"https://www.youtube.com/watch?v={video_id}",
                "title": v.get("title"),
                "description": v.get("description"),
                "upload_date": v.get("upload_date"),
            }
        )
    return results


def main():
    if not CHANNEL_URL:
        raise SystemExit("YOUTUBE_CHANNEL_URL not set in .env")

    videos = fetch_videos(CHANNEL_URL)

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(videos, indent=2, ensure_ascii=False))

    print(f"Fetched {len(videos)} videos -> {OUT_PATH}")


if __name__ == "__main__":
    main()
