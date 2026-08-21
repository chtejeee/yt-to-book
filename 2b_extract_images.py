"""Step 2b — Pull content frames (diagrams, slides, on-screen text) out of each video.

For every video: download a low-res copy, detect scene-change frames with
ffmpeg, ask a local vision model whether each frame is informational content
(vs. just the speaker talking), keep only the informational ones, then
delete the downloaded video. Output: data/images/<video_id>/*.jpg +
images.json (timestamp, caption, duration) per video.
"""
import base64
import json
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

import cv2
import requests
from dotenv import load_dotenv

load_dotenv()

FACE_CASCADE = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")

BASE = Path(__file__).parent
VIDEOS_PATH = BASE / "data" / "videos.json"
IMAGES_DIR = BASE / "data" / "images"

OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://localhost:11434")
VISION_MODEL = os.getenv("VISION_MODEL", "moondream")
SCENE_THRESHOLD = float(os.getenv("SCENE_THRESHOLD", "0.35"))
MAX_FRAMES_PER_VIDEO = int(os.getenv("MAX_FRAMES_PER_VIDEO", "12"))

CONTENT_CHECK_PROMPT = (
    "Does this image contain readable on-screen text, a diagram, a chart, a list, "
    "or another informational graphic? Answer with only one word: YES or NO."
)
CAPTION_PROMPT = (
    "In one short sentence, describe exactly what informational content this image "
    "shows (the on-screen text, diagram, or graphic). Do not mention people."
)


def has_face(image_path: str) -> bool:
    """Hard filter: reject any frame with a detectable face. A small local VQA model
    can't reliably follow "no people" instructions on its own, so this is enforced
    deterministically instead of trusting the model's judgment."""
    img = cv2.imread(image_path)
    if img is None:
        return False
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    faces = FACE_CASCADE.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=5, minSize=(40, 40))
    return len(faces) > 0


def download_video(url: str, out_path: Path) -> bool:
    result = subprocess.run(
        [
            "yt-dlp",
            "-f", "bestvideo[height<=480][ext=mp4]/best[height<=480]",
            "-o", str(out_path),
            "--no-playlist",
            "--quiet",
            url,
        ],
        capture_output=True,
        text=True,
    )
    return result.returncode == 0 and out_path.exists()


def get_duration(video_path: Path) -> float:
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(video_path)],
        capture_output=True,
        text=True,
    )
    try:
        return float(result.stdout.strip())
    except ValueError:
        return 0.0


def extract_scene_frames(video_path: Path, out_dir: Path) -> list[dict]:
    """Extract scene-change frames with their timestamps via ffmpeg's scene filter."""
    out_dir.mkdir(parents=True, exist_ok=True)
    pattern = str(out_dir / "raw_%04d.jpg")
    result = subprocess.run(
        [
            "ffmpeg", "-y", "-i", str(video_path),
            "-vf", f"select='gt(scene,{SCENE_THRESHOLD})',showinfo",
            "-vsync", "vfr",
            "-frame_pts", "true",
            pattern,
        ],
        capture_output=True,
        text=True,
    )
    # Parse timestamps out of showinfo stderr lines: "... pts_time:12.34 ..."
    timestamps = [float(m) for m in re.findall(r"pts_time:([\d.]+)", result.stderr)]
    frames = sorted(out_dir.glob("raw_*.jpg"))
    paired = list(zip(frames, timestamps))
    if len(paired) > MAX_FRAMES_PER_VIDEO:
        step = len(paired) / MAX_FRAMES_PER_VIDEO
        paired = [paired[int(i * step)] for i in range(MAX_FRAMES_PER_VIDEO)]
    return [{"path": p, "timestamp": t} for p, t in paired]


def ask_vision(image_b64: str, prompt: str) -> str:
    response = requests.post(
        f"{OLLAMA_HOST}/api/chat",
        json={
            "model": VISION_MODEL,
            "messages": [{"role": "user", "content": prompt, "images": [image_b64]}],
            "stream": False,
        },
        timeout=120,
    )
    response.raise_for_status()
    return response.json()["message"]["content"].strip()


def caption_or_skip(image_path: Path) -> str | None:
    # Deterministic hard filter first — no LLM call needed to reject a speaker shot.
    if has_face(str(image_path)):
        return None

    b64 = base64.b64encode(image_path.read_bytes()).decode()

    verdict = ask_vision(b64, CONTENT_CHECK_PROMPT).strip().upper()
    if not verdict.startswith("Y"):
        return None

    caption = ask_vision(b64, CAPTION_PROMPT).strip()
    if len(caption) < 3:
        return None
    return caption


def process_video(video: dict) -> list[dict]:
    video_id = video["id"]
    out_dir = IMAGES_DIR / video_id
    manifest_path = out_dir / "images.json"
    if manifest_path.exists():
        return json.loads(manifest_path.read_text())

    with tempfile.TemporaryDirectory() as tmp:
        video_path = Path(tmp) / f"{video_id}.mp4"
        print(f"Downloading {video_id}  {video.get('title', '')}")
        if not download_video(video["url"], video_path):
            print(f"  could not download, skipping")
            manifest_path.parent.mkdir(parents=True, exist_ok=True)
            manifest_path.write_text("[]")
            return []

        duration = get_duration(video_path)
        raw_dir = Path(tmp) / "frames"
        candidates = extract_scene_frames(video_path, raw_dir)
        print(f"  {len(candidates)} candidate frames, screening with {VISION_MODEL}...")

        kept = []
        out_dir.mkdir(parents=True, exist_ok=True)
        for i, frame in enumerate(candidates):
            caption = caption_or_skip(frame["path"])
            if caption is None:
                continue
            filename = f"{int(frame['timestamp']):05d}.jpg"
            shutil.copy(frame["path"], out_dir / filename)
            kept.append({"file": filename, "timestamp": frame["timestamp"], "caption": caption})
            print(f"  kept t={frame['timestamp']:.0f}s: {caption[:70]}")

        manifest = {"duration": duration, "images": kept}
        manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False))
        print(f"  {len(kept)}/{len(candidates)} frames kept -> {manifest_path}")
        return kept


def main():
    if not VIDEOS_PATH.exists():
        raise SystemExit("data/videos.json not found — run 1_fetch_videos.py first")
    if not shutil.which("ffmpeg"):
        raise SystemExit("ffmpeg not found — install it first: brew install ffmpeg")

    videos = json.loads(VIDEOS_PATH.read_text())
    IMAGES_DIR.mkdir(parents=True, exist_ok=True)

    total_kept = 0
    for video in videos:
        kept = process_video(video)
        total_kept += len(kept)

    print(f"\nDone. {total_kept} content images across {len(videos)} videos -> {IMAGES_DIR}")


if __name__ == "__main__":
    main()
