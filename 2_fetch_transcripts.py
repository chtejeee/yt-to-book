"""Step 2 — Fetch transcripts for every video in data/videos.json."""
import json
import sys
from pathlib import Path

from youtube_transcript_api import YouTubeTranscriptApi
from youtube_transcript_api._errors import (
    NoTranscriptFound,
    TranscriptsDisabled,
    VideoUnavailable,
)

BASE = Path(__file__).parent
VIDEOS_PATH = BASE / "data" / "videos.json"
TRANSCRIPTS_DIR = BASE / "data" / "transcripts"
SKIPPED_PATH = BASE / "data" / "skipped.json"


def fetch_transcript_text(api: YouTubeTranscriptApi, video_id: str) -> str:
    transcript_list = api.list(video_id)

    try:
        transcript = transcript_list.find_manually_created_transcript(["en"])
    except NoTranscriptFound:
        transcript = transcript_list.find_generated_transcript(["en"])

    fetched = transcript.fetch()
    return "\n".join(snippet.text for snippet in fetched)


def main():
    if not VIDEOS_PATH.exists():
        raise SystemExit("data/videos.json not found — run 1_fetch_videos.py first")

    videos = json.loads(VIDEOS_PATH.read_text())
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

        try:
            text = fetch_transcript_text(api, video_id)
            out_path.write_text(text, encoding="utf-8")
            fetched_count += 1
            print(f"OK    {video_id}  {v.get('title', '')}")
        except (TranscriptsDisabled, NoTranscriptFound, VideoUnavailable) as e:
            skipped.append({"id": video_id, "title": v.get("title"), "reason": str(e)})
            print(f"SKIP  {video_id}  {e.__class__.__name__}", file=sys.stderr)
        except Exception as e:
            skipped.append({"id": video_id, "title": v.get("title"), "reason": str(e)})
            print(f"ERROR {video_id}  {e}", file=sys.stderr)

    SKIPPED_PATH.write_text(json.dumps(skipped, indent=2, ensure_ascii=False))
    print(f"\nFetched {fetched_count}/{len(videos)} transcripts. Skipped {len(skipped)} -> {SKIPPED_PATH}")


if __name__ == "__main__":
    main()
