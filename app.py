"""Simple web UI to drive the yt-to-book pipeline.

Takes a YouTube channel URL, saves it to .env, and runs the four
pipeline steps (fetch videos -> transcripts -> chapters -> docx) with
their output shown in the browser.
"""
import json
import subprocess
import sys
from pathlib import Path

from dotenv import get_key, set_key
from flask import Flask, redirect, render_template_string, send_file, url_for

BASE = Path(__file__).parent
ENV_PATH = BASE / ".env"
VIDEOS_PATH = BASE / "data" / "videos.json"
TRANSCRIPTS_DIR = BASE / "data" / "transcripts"
CHAPTERS_DIR = BASE / "data" / "chapters"
DOCX_PATH = BASE / "output" / "book.docx"
PDF_PATH = BASE / "output" / "book.pdf"

STEPS = [
    ("1_fetch_videos.py", "Fetch Videos"),
    ("2_fetch_transcripts.py", "Fetch Transcripts"),
    ("3_build_book.py", "Build Book"),
    ("4_export_docx.py", "Export DOCX"),
    ("5_export_pdf.py", "Export PDF"),
]

app = Flask(__name__)

PAGE = """
<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <title>yt-to-book</title>
  <style>
    body { font-family: -apple-system, sans-serif; max-width: 760px; margin: 40px auto; padding: 0 16px; color: #222; }
    h1 { font-size: 22px; }
    .card { border: 1px solid #ddd; border-radius: 8px; padding: 16px; margin-bottom: 16px; }
    input[type=text] { width: 100%; padding: 8px; box-sizing: border-box; font-size: 14px; }
    button { padding: 8px 14px; font-size: 14px; cursor: pointer; margin-top: 8px; margin-right: 8px; }
    .status { font-size: 14px; color: #444; }
    .ok { color: #1a7f37; }
    .pending { color: #999; }
    pre { background: #111; color: #ddd; padding: 12px; border-radius: 6px; overflow-x: auto; white-space: pre-wrap; }
    a.download { display: inline-block; margin-top: 8px; }
  </style>
</head>
<body>
  <h1>yt-to-book</h1>

  <div class="card">
    <form method="post" action="{{ url_for('set_channel') }}">
      <label>YouTube channel URL</label>
      <input type="text" name="channel_url" value="{{ channel_url }}" placeholder="https://www.youtube.com/@channelname">
      <button type="submit">Save</button>
    </form>
  </div>

  <div class="card">
    <div class="status">Videos: <span class="{{ 'ok' if video_count else 'pending' }}">{{ video_count }}</span></div>
    <div class="status">Transcripts: <span class="{{ 'ok' if transcript_count else 'pending' }}">{{ transcript_count }}</span></div>
    <div class="status">Chapters: <span class="{{ 'ok' if chapter_count else 'pending' }}">{{ chapter_count }}</span></div>
    <div class="status">DOCX: <span class="{{ 'ok' if docx_exists else 'pending' }}">{{ 'ready' if docx_exists else 'not built' }}</span></div>
    <div class="status">PDF: <span class="{{ 'ok' if pdf_exists else 'pending' }}">{{ 'ready' if pdf_exists else 'not built' }}</span></div>
    {% if docx_exists %}
      <a class="download" href="{{ url_for('download_docx') }}">Download book.docx</a><br>
    {% endif %}
    {% if pdf_exists %}
      <a class="download" href="{{ url_for('download_pdf') }}">Download book.pdf</a>
    {% endif %}
  </div>

  <div class="card">
    {% for script, label in steps %}
      <form method="post" action="{{ url_for('run_step', script=script) }}" style="display:inline;">
        <button type="submit">Run: {{ label }}</button>
      </form>
    {% endfor %}
    <form method="post" action="{{ url_for('run_all') }}" style="display:inline;">
      <button type="submit">Run All</button>
    </form>
  </div>

  {% if log %}
  <div class="card">
    <strong>{{ log_title }}</strong>
    <pre>{{ log }}</pre>
  </div>
  {% endif %}
</body>
</html>
"""


def count_json(path: Path) -> int:
    if not path.exists():
        return 0
    return len(json.loads(path.read_text()))


def render(log_title: str = "", log: str = ""):
    channel_url = get_key(str(ENV_PATH), "YOUTUBE_CHANNEL_URL") or ""
    return render_template_string(
        PAGE,
        channel_url=channel_url,
        video_count=count_json(VIDEOS_PATH),
        transcript_count=len(list(TRANSCRIPTS_DIR.glob("*.txt"))) if TRANSCRIPTS_DIR.exists() else 0,
        chapter_count=len(list(CHAPTERS_DIR.glob("*.txt"))) if CHAPTERS_DIR.exists() else 0,
        docx_exists=DOCX_PATH.exists(),
        pdf_exists=PDF_PATH.exists(),
        steps=STEPS,
        log_title=log_title,
        log=log,
    )


@app.route("/")
def index():
    return render()


@app.route("/set-channel", methods=["POST"])
def set_channel():
    from flask import request

    channel_url = request.form.get("channel_url", "").strip()
    if channel_url:
        set_key(str(ENV_PATH), "YOUTUBE_CHANNEL_URL", channel_url)
    return redirect(url_for("index"))


def run_script(script: str) -> str:
    result = subprocess.run(
        [sys.executable, str(BASE / script)],
        cwd=str(BASE),
        capture_output=True,
        text=True,
    )
    output = result.stdout + result.stderr
    if result.returncode != 0:
        output += f"\n\n[exited with code {result.returncode}]"
    return output


@app.route("/run/<script>", methods=["POST"])
def run_step(script):
    if script not in {s for s, _ in STEPS}:
        return redirect(url_for("index"))
    output = run_script(script)
    return render(log_title=f"Output: {script}", log=output)


@app.route("/run-all", methods=["POST"])
def run_all():
    logs = []
    for script, label in STEPS:
        logs.append(f"=== {label} ({script}) ===\n{run_script(script)}")
        if "[exited with code" in logs[-1]:
            break
    return render(log_title="Output: Run All", log="\n\n".join(logs))


@app.route("/download/docx")
def download_docx():
    return send_file(DOCX_PATH, as_attachment=True)


@app.route("/download/pdf")
def download_pdf():
    return send_file(PDF_PATH, as_attachment=True)


if __name__ == "__main__":
    app.run(debug=True, port=5050)
