# yt-to-book

Turn a YouTube channel's videos into a formatted book (PDF + DOCX). Fetches
every video, pulls transcripts, rewrites each one into a book chapter with an
LLM, then typesets the result.

## Pipeline

| Step | Script | What it does |
|---|---|---|
| 1 | `1_fetch_videos.py` | Lists every video on the channel (id, url, title, description, upload date) via yt-dlp |
| 2 | `2_fetch_transcripts.py` | Downloads a transcript per video (manual captions, falling back to auto-generated) |
| 3 | `3_build_book.py` | Rewrites each transcript into a structured chapter (intro / body / takeaways) |
| 4 | `4_export_docx.py` | Combines all chapters into a single `.docx` with cover, TOC, and appendix |
| 5 | `5_export_pdf.py` | Typesets a print-quality `.pdf` — serif body text, dot-leader TOC, chapter title pages, drop caps, running headers |

Each script reads from / writes to `data/` and can be re-run independently
(already-processed videos, transcripts, and chapters are skipped).

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # then fill in the values below
```

### `.env`

```
YOUTUBE_CHANNEL_URL=https://www.youtube.com/@channelname

# Backend for Step 3 — pick one
BACKEND=ollama                 # local, free, private
OLLAMA_MODEL=llama3.2
OLLAMA_HOST=http://localhost:11434

# BACKEND=anthropic            # hosted, needs a paid API key
# ANTHROPIC_API_KEY=your_key_here

# Optional cover/branding
BOOK_TITLE=
BOOK_SUBTITLE=
BOOK_BYLINE=
PDF_ACCENT=#B5533C
PDF_ACCENT_DARK=#7A3229
```

**Local backend (default):** install [Ollama](https://ollama.com), pull a
small instruction-tuned model, and leave `BACKEND=ollama`:

```bash
ollama pull llama3.2
ollama serve
```

**Hosted backend:** set `BACKEND=anthropic` and add a real
`ANTHROPIC_API_KEY` from your API provider's console (this is separate from
any chat subscription — it's billed independently, pay-as-you-go).

## Run

```bash
python 1_fetch_videos.py
python 2_fetch_transcripts.py
python 3_build_book.py
python 4_export_docx.py
python 5_export_pdf.py
```

Or drive it from the browser:

```bash
python app.py   # http://localhost:5050
```

The UI lets you set the channel URL, run any step (or all of them), watch
live output, and download the finished `book.docx` / `book.pdf`.

## Output

```
output/
  book.docx
  book.pdf
```

## Notes

- No YouTube API key required — video listing and transcripts both use
  public, unauthenticated endpoints.
- Videos without any transcript are skipped and logged to `data/skipped.json`.
- Long transcripts (>8000 tokens with the hosted backend, >3000 with the
  local one) are chunked automatically before being sent to the model.
