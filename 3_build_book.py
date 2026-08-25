"""Step 3 — Turn each transcript into a structured book chapter via an LLM.

Backend is selected by BACKEND in .env:
  BACKEND=anthropic  -> Claude API (needs ANTHROPIC_API_KEY)
  BACKEND=ollama      -> local Ollama server (needs `ollama serve` running)
"""
import json
import os
import time
from pathlib import Path

import requests
from dotenv import load_dotenv

load_dotenv()

BASE = Path(__file__).parent
VIDEOS_PATH = BASE / "data" / "videos.json"
SELECTED_PATH = BASE / "data" / "selected.json"
TRANSCRIPTS_DIR = BASE / "data" / "transcripts"
CHAPTERS_DIR = BASE / "data" / "chapters"


def load_selected_ids(all_ids: set[str]) -> set[str]:
    """Restrict to the videos picked in the UI, if a selection was saved. With no
    selection.json (e.g. CLI-only use), every fetched video is included."""
    if not SELECTED_PATH.exists():
        return all_ids
    return set(json.loads(SELECTED_PATH.read_text())) & all_ids

BACKEND = os.getenv("BACKEND", "anthropic").lower()

CLAUDE_MODEL = os.getenv("CLAUDE_MODEL", "claude-sonnet-5")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "llama3.2")
OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://localhost:11434")
OLLAMA_NUM_CTX = 8192

MAX_TOKENS = 2000
# Local 3b-class models have a small reliable context window — keep chunks smaller than the API path.
CHUNK_TOKEN_LIMIT = 3000 if BACKEND == "ollama" else 8000
CHARS_PER_TOKEN = 4
DELAY_SECONDS = 1.5

SYSTEM_PROMPT = (
    "You are an expert editor converting YouTube video transcripts into book chapters. "
    "Write in clear, engaging prose. Remove filler words and repetition. "
    "Structure each chapter with: Introduction, Main Content (with subheadings), Key Takeaways. "
    "Maintain a consistent, authoritative tone throughout."
)

CHUNK_CLEAN_PROMPT = (
    "This is one part of a longer video transcript. Clean up filler words and noise, "
    "and extract the key points and insights as clear prose notes. Do not add chapter "
    "formatting yet — just cleaned, condensed notes for this part."
)


def estimate_tokens(text: str) -> int:
    return len(text) // CHARS_PER_TOKEN


def split_into_chunks(text: str, token_limit: int) -> list[str]:
    char_limit = token_limit * CHARS_PER_TOKEN
    return [text[i : i + char_limit] for i in range(0, len(text), char_limit)]


def call_claude(client, system: str, user_content: str, max_tokens: int) -> str:
    response = client.messages.create(
        model=CLAUDE_MODEL,
        max_tokens=max_tokens,
        system=system,
        messages=[{"role": "user", "content": user_content}],
    )
    return "".join(block.text for block in response.content if block.type == "text")


def call_ollama(system: str, user_content: str, max_tokens: int) -> str:
    response = requests.post(
        f"{OLLAMA_HOST}/api/chat",
        json={
            "model": OLLAMA_MODEL,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user_content},
            ],
            "stream": False,
            "options": {"num_predict": max_tokens, "num_ctx": OLLAMA_NUM_CTX},
        },
        timeout=600,
    )
    response.raise_for_status()
    return response.json()["message"]["content"]


def call_model(client, system: str, user_content: str, max_tokens: int) -> str:
    if BACKEND == "ollama":
        return call_ollama(system, user_content, max_tokens)
    return call_claude(client, system, user_content, max_tokens)


def build_chapter(client, title: str, transcript: str) -> str:
    if estimate_tokens(transcript) > CHUNK_TOKEN_LIMIT:
        chunks = split_into_chunks(transcript, CHUNK_TOKEN_LIMIT)
        notes = []
        for i, chunk in enumerate(chunks, 1):
            notes.append(call_model(client, CHUNK_CLEAN_PROMPT, chunk, max_tokens=1024))
            time.sleep(DELAY_SECONDS)
        combined = "\n\n".join(notes)
        user_content = (
            f"Video title: {title}\n\nCleaned notes from the full transcript:\n\n{combined}\n\n"
            "Write this as a complete book chapter following the system instructions. "
            "Start with a suggested chapter title on the first line as '# Title'."
        )
    else:
        user_content = (
            f"Video title: {title}\n\nRaw transcript:\n\n{transcript}\n\n"
            "Write this as a complete book chapter following the system instructions. "
            "Start with a suggested chapter title on the first line as '# Title'."
        )

    return call_model(client, SYSTEM_PROMPT, user_content, max_tokens=MAX_TOKENS)


def setup_backend():
    if BACKEND == "ollama":
        try:
            requests.get(f"{OLLAMA_HOST}/api/tags", timeout=5)
        except requests.exceptions.ConnectionError:
            raise SystemExit(
                f"Can't reach Ollama at {OLLAMA_HOST} — run `ollama serve` (or `ollama run {OLLAMA_MODEL}`) first"
            )
        return None

    import anthropic

    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key or api_key == "your_key_here":
        raise SystemExit("ANTHROPIC_API_KEY not set in .env — add a real key before running Step 3")
    return anthropic.Anthropic(api_key=api_key)


def main():
    if not VIDEOS_PATH.exists():
        raise SystemExit("data/videos.json not found — run 1_fetch_videos.py first")

    client = setup_backend()
    model_name = OLLAMA_MODEL if BACKEND == "ollama" else CLAUDE_MODEL
    print(f"Backend: {BACKEND} ({model_name})")

    videos = {v["id"]: v for v in json.loads(VIDEOS_PATH.read_text())}
    CHAPTERS_DIR.mkdir(parents=True, exist_ok=True)

    # Scope to the current selection only — data/transcripts/ accumulates across every
    # book ever built, so a plain glob would pull in transcripts from other channels/playlists.
    scope = load_selected_ids(set(videos))
    transcript_files = [TRANSCRIPTS_DIR / f"{vid}.txt" for vid in scope if (TRANSCRIPTS_DIR / f"{vid}.txt").exists()]
    if not transcript_files:
        raise SystemExit("No transcripts found in data/transcripts/ — run 2_fetch_transcripts.py first")

    built = 0
    for path in transcript_files:
        video_id = path.stem
        out_path = CHAPTERS_DIR / f"{video_id}.txt"
        if out_path.exists():
            built += 1
            continue

        title = videos.get(video_id, {}).get("title", video_id)
        transcript = path.read_text(encoding="utf-8")

        print(f"Building chapter for {video_id}  {title}")
        chapter = build_chapter(client, title, transcript)
        out_path.write_text(chapter, encoding="utf-8")
        built += 1
        time.sleep(DELAY_SECONDS)

    print(f"\nBuilt {built}/{len(transcript_files)} chapters -> {CHAPTERS_DIR}")


if __name__ == "__main__":
    main()
