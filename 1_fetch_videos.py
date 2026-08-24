"""Step 1 — Fetch all video URLs and metadata from a YouTube channel or playlist via yt-dlp."""
import json
import os
import re
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import yt_dlp
from dotenv import load_dotenv

load_dotenv()

CHANNEL_URL = os.getenv("YOUTUBE_CHANNEL_URL")
OUT_PATH = Path(__file__).parent / "data" / "videos.json"
SOURCE_PATH = Path(__file__).parent / "data" / "source.json"


def normalize_url(url: str) -> str:
    """A "watch?v=X&list=Y" URL (the common way people copy a playlist link while a
    video is playing) resolves to just that one video in yt-dlp's flat-extract mode —
    it doesn't expand to the full playlist. Rewrite it to the canonical
    "playlist?list=Y" form, which does."""
    parsed = urlparse(url)
    list_id = parse_qs(parsed.query).get("list", [None])[0]
    if list_id and parsed.path.rstrip("/") == "/watch":
        return f"https://www.youtube.com/playlist?list={list_id}"
    return url


def slugify(text: str, max_len: int = 60) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return slug[:max_len].rstrip("-") or "book"


def fetch_videos(channel_url: str) -> tuple[str, list[dict]]:
    """Returns (source_title, videos) — source_title is the channel/playlist name,
    used downstream to name the book and its output files."""
    channel_url = normalize_url(channel_url)
    ydl_opts = {
        "extract_flat": True,
        "quiet": True,
        "skip_download": True,
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(channel_url, download=False)

    source_title = info.get("title") or "Book"
    # yt-dlp appends the tab name to channel titles (e.g. "Dr Arif Khan - Videos") — strip it.
    source_title = re.sub(
        r"\s*-\s*(Videos|Playlists|Shorts|Live|Community|Posts|Streams)$", "", source_title, flags=re.I
    ).strip()

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
    return source_title, results


def main():
    if not CHANNEL_URL:
        raise SystemExit("YOUTUBE_CHANNEL_URL not set in .env")

    source_title, videos = fetch_videos(CHANNEL_URL)

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(videos, indent=2, ensure_ascii=False))
    SOURCE_PATH.write_text(
        json.dumps({"title": source_title, "slug": slugify(source_title)}, indent=2, ensure_ascii=False)
    )

    print(f"Fetched {len(videos)} videos from '{source_title}' -> {OUT_PATH}")


if __name__ == "__main__":
    main()
