"""Step 2 — Fetch transcripts for every video in data/videos.json.

Tries youtube-transcript-api first (fast, no download). If that fails for any
reason — IP-blocked, no captions, disabled, etc. — falls back to downloading
the audio with yt-dlp and transcribing it locally with Whisper. The fallback
never depends on YouTube's transcript endpoint, so it works even when that's
rate-limited or the video simply has no captions.
"""
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from dotenv import load_dotenv
from youtube_transcript_api import YouTubeTranscriptApi
from youtube_transcript_api._errors import (
    IpBlocked,
    NoTranscriptFound,
    RequestBlocked,
    TranscriptsDisabled,
    VideoUnavailable,
)

load_dotenv()

BASE = Path(__file__).parent
VIDEOS_PATH = BASE / "data" / "videos.json"
SELECTED_PATH = BASE / "data" / "selected.json"
TRANSCRIPTS_DIR = BASE / "data" / "transcripts"
SKIPPED_PATH = BASE / "data" / "skipped.json"


def load_selected(videos: list[dict]) -> list[dict]:
    """Restrict to the videos picked in the UI, if a selection was saved. With no
    selection.json (e.g. CLI-only use), every fetched video is included."""
    if not SELECTED_PATH.exists():
        return videos
    selected = set(json.loads(SELECTED_PATH.read_text()))
    return [v for v in videos if v["id"] in selected]

REQUEST_DELAY_SECONDS = 2
MAX_RETRIES = 2
RETRY_BACKOFF_SECONDS = [15, 45]

WHISPER_MODEL = os.getenv("WHISPER_MODEL", "base")
_whisper = None  # lazy-loaded — only pay the load cost if the fallback is actually needed


def get_whisper():
    global _whisper
    if _whisper is None:
        from faster_whisper import WhisperModel

        print(f"  loading Whisper model '{WHISPER_MODEL}' (first fallback use)...", file=sys.stderr)
        _whisper = WhisperModel(WHISPER_MODEL, device="cpu", compute_type="int8")
    return _whisper


def fetch_transcript_text(api: YouTubeTranscriptApi, video_id: str) -> str:
    transcript_list = api.list(video_id)

    try:
        transcript = transcript_list.find_manually_created_transcript(["en"])
    except NoTranscriptFound:
        transcript = transcript_list.find_generated_transcript(["en"])

    fetched = transcript.fetch()
    return "\n".join(snippet.text for snippet in fetched)


def fetch_via_api(api: YouTubeTranscriptApi, video_id: str) -> str | None:
    """Returns transcript text, or None if it should fall back to Whisper."""
    for attempt in range(MAX_RETRIES + 1):
        try:
            return fetch_transcript_text(api, video_id)
        except (IpBlocked, RequestBlocked):
            if attempt == MAX_RETRIES:
                return None
            wait = RETRY_BACKOFF_SECONDS[min(attempt, len(RETRY_BACKOFF_SECONDS) - 1)]
            print(f"  rate-limited, retrying {video_id} in {wait}s (attempt {attempt + 1}/{MAX_RETRIES})",
                  file=sys.stderr)
            time.sleep(wait)
        except (TranscriptsDisabled, NoTranscriptFound, VideoUnavailable):
            return None


def fetch_via_whisper(url: str, video_id: str) -> str:
    with tempfile.TemporaryDirectory() as tmp:
        audio_path = Path(tmp) / f"{video_id}.m4a"
        result = subprocess.run(
            [
                "yt-dlp", "-f", "bestaudio[ext=m4a]/bestaudio",
                "-o", str(audio_path), "--no-playlist", "--quiet", url,
            ],
            capture_output=True, text=True,
        )
        if result.returncode != 0 or not audio_path.exists():
            raise RuntimeError(f"yt-dlp audio download failed: {result.stderr[:300]}")

        model = get_whisper()
        segments, _ = model.transcribe(str(audio_path), beam_size=1)
        return "\n".join(seg.text.strip() for seg in segments)


def main():
    if not VIDEOS_PATH.exists():
        raise SystemExit("data/videos.json not found — run 1_fetch_videos.py first")

    videos = load_selected(json.loads(VIDEOS_PATH.read_text()))
    TRANSCRIPTS_DIR.mkdir(parents=True, exist_ok=True)

    api = YouTubeTranscriptApi()
    skipped = []
    fetched_count = 0

    for v in videos:
        video_id = v["id"]
        out_path = TRANSCRIPTS_DIR / f"{video_id}.txt"
        if out_path.exists():
            fetched_count += 1
            continue

        text = fetch_via_api(api, video_id)
        source = "captions"

        if text is None:
            print(f"  no captions available for {video_id}, falling back to Whisper", file=sys.stderr)
            try:
                text = fetch_via_whisper(v["url"], video_id)
                source = "whisper"
            except Exception as e:
                skipped.append({"id": video_id, "title": v.get("title"), "reason": str(e)})
                print(f"ERROR {video_id}  Whisper fallback also failed: {e}", file=sys.stderr)
                time.sleep(REQUEST_DELAY_SECONDS)
                continue

        out_path.write_text(text, encoding="utf-8")
        fetched_count += 1
        print(f"OK    {video_id}  [{source}]  {v.get('title', '')}")
        time.sleep(REQUEST_DELAY_SECONDS)

    SKIPPED_PATH.write_text(json.dumps(skipped, indent=2, ensure_ascii=False))
    print(f"\nFetched {fetched_count}/{len(videos)} transcripts. Skipped {len(skipped)} -> {SKIPPED_PATH}")


if __name__ == "__main__":
    main()
