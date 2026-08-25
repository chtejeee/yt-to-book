"""Simple web UI to drive the yt-to-book pipeline.

Takes a YouTube channel URL, saves it to .env, and runs the pipeline steps
(fetch videos -> transcripts -> chapters -> docx/pdf) with their output
streamed live in the browser. After fetching videos, pick which ones
actually go into the book — every later step respects that selection.
A History page lists every book ever built, with one-click PDF/DOCX access.
"""
import json
import subprocess
import sys
import threading
from pathlib import Path

from dotenv import get_key, set_key
from flask import Flask, jsonify, redirect, render_template_string, request, send_file, url_for

BASE = Path(__file__).parent
ENV_PATH = BASE / ".env"
VIDEOS_PATH = BASE / "data" / "videos.json"
SELECTED_PATH = BASE / "data" / "selected.json"
TRANSCRIPTS_DIR = BASE / "data" / "transcripts"
CHAPTERS_DIR = BASE / "data" / "chapters"
SOURCE_PATH = BASE / "data" / "source.json"
HISTORY_PATH = BASE / "data" / "history.json"
OUTPUT_DIR = BASE / "output"


def current_slug() -> str:
    if SOURCE_PATH.exists():
        return json.loads(SOURCE_PATH.read_text()).get("slug", "book")
    return "book"


def docx_path(slug: str | None = None) -> Path:
    return OUTPUT_DIR / f"{slug or current_slug()}.docx"


def pdf_path(slug: str | None = None) -> Path:
    return OUTPUT_DIR / f"{slug or current_slug()}.pdf"


STEPS = [
    ("1_fetch_videos.py", "Fetch Videos"),
    ("2_fetch_transcripts.py", "Fetch Transcripts"),
    ("3_build_book.py", "Build Book"),
    ("4_export_docx.py", "Export DOCX"),
    ("5_export_pdf.py", "Export PDF"),
]
STEP_SCRIPTS = {s for s, _ in STEPS}

# --- Background run state ---------------------------------------------------
RUN_LOCK = threading.Lock()
RUN_STATE = {
    "running": False,
    "label": "",
    "output": "",
    "process": None,
    "stop_requested": False,
}


def _append(text: str):
    with RUN_LOCK:
        RUN_STATE["output"] += text


def _run_one(script: str, label: str) -> bool:
    """Runs one script to completion, streaming its output live. Returns False
    if the run should stop here (user hit Stop, or the script failed)."""
    with RUN_LOCK:
        if RUN_STATE["stop_requested"]:
            return False
    _append(f"\n=== {label} ({script}) ===\n")
    proc = subprocess.Popen(
        [sys.executable, str(BASE / script)],
        cwd=str(BASE),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )
    with RUN_LOCK:
        RUN_STATE["process"] = proc

    for line in proc.stdout:
        _append(line)
        with RUN_LOCK:
            if RUN_STATE["stop_requested"] and proc.poll() is None:
                proc.terminate()

    proc.wait()
    with RUN_LOCK:
        RUN_STATE["process"] = None
    if proc.returncode != 0:
        reason = "stopped by user" if RUN_STATE["stop_requested"] else f"exited with code {proc.returncode}"
        _append(f"\n[{reason}]\n")
        return False
    return True


def _finish():
    with RUN_LOCK:
        RUN_STATE["running"] = False
        RUN_STATE["label"] = ""


def _worker_single(script: str, label: str):
    _run_one(script, label)
    _finish()


def _worker_all():
    for script, label in STEPS:
        with RUN_LOCK:
            if RUN_STATE["stop_requested"]:
                break
        if not _run_one(script, label):
            break
    _finish()


def start_run(target, *args) -> bool:
    with RUN_LOCK:
        if RUN_STATE["running"]:
            return False
        RUN_STATE["running"] = True
        RUN_STATE["output"] = ""
        RUN_STATE["stop_requested"] = False
        RUN_STATE["label"] = args[-1] if args else "Run All"
    threading.Thread(target=target, args=args, daemon=True).start()
    return True


app = Flask(__name__)

BASE_STYLE = """
    body { font-family: -apple-system, sans-serif; max-width: 820px; margin: 40px auto; padding: 0 16px; color: #222; }
    h1 { font-size: 22px; }
    nav { margin-bottom: 20px; font-size: 14px; }
    nav a { margin-right: 16px; color: #1a5fb4; text-decoration: none; }
    .card { border: 1px solid #ddd; border-radius: 8px; padding: 16px; margin-bottom: 16px; }
    input[type=text] { width: 100%; padding: 8px; box-sizing: border-box; font-size: 14px; }
    button { padding: 8px 14px; font-size: 14px; cursor: pointer; margin-top: 8px; margin-right: 8px; }
    button:disabled { opacity: 0.5; cursor: default; }
    button.stop { background: #d92d20; color: white; border: none; border-radius: 4px; }
    .status { font-size: 14px; color: #444; }
    .ok { color: #1a7f37; }
    .pending { color: #999; }
    pre { background: #111; color: #ddd; padding: 12px; border-radius: 6px; overflow-x: auto; white-space: pre-wrap; max-height: 360px; overflow-y: auto; }
    a.download { display: inline-block; margin-top: 8px; }
    table { width: 100%; border-collapse: collapse; font-size: 13px; }
    th, td { text-align: left; padding: 8px 6px; border-bottom: 1px solid #eee; vertical-align: top; }
    th { color: #666; font-weight: 600; }
    .muted { color: #888; font-size: 12px; }
    .running-badge { display: inline-block; padding: 2px 8px; border-radius: 10px; background: #fff4e5; color: #b25e00; font-size: 12px; margin-left: 8px; }
"""

PAGE = """
<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <title>yt-to-book</title>
  <style>
    {{ base_style }}
    .picker-search { margin: 10px 0 8px; }
    .picker { display: flex; gap: 10px; align-items: stretch; }
    .picker-col { flex: 1; min-width: 0; border: 1px solid #eee; border-radius: 6px; display: flex; flex-direction: column; }
    .picker-col h4 { margin: 0; padding: 8px 10px; font-size: 12px; color: #666; border-bottom: 1px solid #eee; background: #fafafa; }
    .picker-items { max-height: 340px; overflow-y: auto; }
    .picker-item { padding: 6px 10px; font-size: 13px; cursor: pointer; border-bottom: 1px solid #f5f5f5; }
    .picker-item:hover { background: #eef4ff; }
    .picker-mid { display: flex; flex-direction: column; justify-content: center; gap: 8px; }
    .picker-mid button { margin: 0; white-space: nowrap; }
  </style>
</head>
<body>
  <h1>yt-to-book</h1>
  <nav><a href="{{ url_for('index') }}">Pipeline</a><a href="{{ url_for('history') }}">History</a></nav>

  <div class="card">
    <form method="post" action="{{ url_for('set_channel') }}">
      <label>YouTube channel URL</label>
      <input type="text" name="channel_url" value="{{ channel_url }}" placeholder="https://www.youtube.com/@channelname">
      <button type="submit">Save</button>
    </form>
  </div>

  {% if videos %}
  <div class="card">
    <strong>Videos ({{ videos|length }} fetched)</strong> — click a title to move it between boxes.
    <form id="selection-form" method="post" action="{{ url_for('save_selection') }}">
      <div id="hidden-inputs"></div>
      <div class="picker-search">
        <input type="text" id="search-box" placeholder="Search video titles...">
      </div>
      <div class="picker">
        <div class="picker-col">
          <h4>Available (<span id="avail-count"></span>)</h4>
          <div class="picker-items" id="available-list"></div>
        </div>
        <div class="picker-mid">
          <button type="button" onclick="addAllVisible()">Add all &raquo;</button>
          <button type="button" onclick="clearIncluded()">&laquo; Clear</button>
        </div>
        <div class="picker-col">
          <h4>Included in book (<span id="incl-count"></span>)</h4>
          <div class="picker-items" id="included-list"></div>
        </div>
      </div>
      <button type="submit">Save Selection</button>
    </form>
  </div>

  <script>
    const ALL_VIDEOS = {{ videos | tojson }};
    let included = new Set({{ selected_ids | list | tojson }});

    function label(v) { return v.title || v.id; }

    function renderPicker() {
      const q = document.getElementById('search-box').value.toLowerCase();
      const availDiv = document.getElementById('available-list');
      const inclDiv = document.getElementById('included-list');
      availDiv.innerHTML = '';
      inclDiv.innerHTML = '';
      let availCount = 0, inclCount = 0;

      for (const v of ALL_VIDEOS) {
        const row = document.createElement('div');
        row.className = 'picker-item';
        row.textContent = label(v);
        if (included.has(v.id)) {
          inclCount++;
          row.onclick = () => { included.delete(v.id); renderPicker(); };
          inclDiv.appendChild(row);
        } else {
          if (q && !label(v).toLowerCase().includes(q)) continue;
          availCount++;
          row.onclick = () => { included.add(v.id); renderPicker(); };
          availDiv.appendChild(row);
        }
      }
      document.getElementById('avail-count').textContent = availCount;
      document.getElementById('incl-count').textContent = inclCount;

      const hidden = document.getElementById('hidden-inputs');
      hidden.innerHTML = '';
      for (const id of included) {
        const inp = document.createElement('input');
        inp.type = 'hidden';
        inp.name = 'video_id';
        inp.value = id;
        hidden.appendChild(inp);
      }
    }

    function addAllVisible() {
      const q = document.getElementById('search-box').value.toLowerCase();
      for (const v of ALL_VIDEOS) {
        if (!q || label(v).toLowerCase().includes(q)) included.add(v.id);
      }
      renderPicker();
    }
    function clearIncluded() { included.clear(); renderPicker(); }

    document.getElementById('search-box').addEventListener('input', renderPicker);
    renderPicker();
  </script>
  {% endif %}

  <div class="card">
    <div class="status">Videos: <span id="stat-videos" class="{{ 'ok' if video_count else 'pending' }}">{{ video_count }}</span></div>
    <div class="status">Selected: <span id="stat-selected" class="{{ 'ok' if selected_count else 'pending' }}">{{ selected_count }}</span></div>
    <div class="status">Transcripts: <span id="stat-transcripts" class="{{ 'ok' if transcript_count else 'pending' }}">{{ transcript_count }}</span> / <span id="stat-selected2">{{ selected_count }}</span> selected</div>
    <div class="status">Chapters: <span id="stat-chapters" class="{{ 'ok' if chapter_count else 'pending' }}">{{ chapter_count }}</span> / <span id="stat-selected3">{{ selected_count }}</span> selected</div>
    <div class="status">DOCX: <span id="stat-docx" class="{{ 'ok' if docx_exists else 'pending' }}">{{ 'ready' if docx_exists else 'not built' }}</span></div>
    <div class="status">PDF: <span id="stat-pdf" class="{{ 'ok' if pdf_exists else 'pending' }}">{{ 'ready' if pdf_exists else 'not built' }}</span></div>
    <div id="download-links">
      {% if docx_exists %}<a class="download" id="dl-docx" href="{{ url_for('download_docx') }}">Download {{ docx_name }}</a><br>{% endif %}
      {% if pdf_exists %}<a class="download" id="dl-pdf" href="{{ url_for('download_pdf') }}">Download {{ pdf_name }}</a>{% endif %}
    </div>
  </div>

  <div class="card">
    <div id="run-buttons">
      {% for script, lbl in steps %}
        <button type="button" class="run-btn" data-script="{{ script }}" data-label="{{ lbl }}" onclick="startRun(this.dataset.script, this.dataset.label)">Run: {{ lbl }}</button>
      {% endfor %}
      <button type="button" id="run-all-btn" onclick="startRunAll()">Run All</button>
      <button type="button" id="stop-btn" class="stop" onclick="stopRun()" style="display:none;">Stop</button>
    </div>
    <span id="running-badge" class="running-badge" style="display:none;"></span>
  </div>

  <div class="card" id="log-card" style="display:none;">
    <strong id="log-title">Output</strong>
    <pre id="log-output"></pre>
  </div>

  <script>
    async function startRun(script, lbl) {
      await fetch(`/start/${script}`, {method: 'POST'});
      poll();
    }
    async function startRunAll() {
      await fetch('/start-all', {method: 'POST'});
      poll();
    }
    async function stopRun() {
      await fetch('/stop', {method: 'POST'});
    }

    let polling = false;
    async function poll() {
      if (polling) return;
      polling = true;
      const timer = setInterval(async () => {
        const res = await fetch('/status');
        const s = await res.json();

        document.getElementById('log-card').style.display = s.output ? 'block' : 'none';
        document.getElementById('log-output').textContent = s.output;
        document.getElementById('log-output').scrollTop = document.getElementById('log-output').scrollHeight;
        document.getElementById('log-title').textContent = s.running ? `Running: ${s.label}...` : 'Output';

        document.querySelectorAll('.run-btn, #run-all-btn').forEach(b => b.disabled = s.running);
        document.getElementById('stop-btn').style.display = s.running ? 'inline-block' : 'none';
        const badge = document.getElementById('running-badge');
        badge.style.display = s.running ? 'inline-block' : 'none';
        badge.textContent = s.running ? s.label : '';

        document.getElementById('stat-videos').textContent = s.video_count;
        document.getElementById('stat-selected').textContent = s.selected_count;
        document.getElementById('stat-selected2').textContent = s.selected_count;
        document.getElementById('stat-selected3').textContent = s.selected_count;
        document.getElementById('stat-transcripts').textContent = s.transcript_count;
        document.getElementById('stat-chapters').textContent = s.chapter_count;
        document.getElementById('stat-docx').textContent = s.docx_exists ? 'ready' : 'not built';
        document.getElementById('stat-docx').className = s.docx_exists ? 'ok' : 'pending';
        document.getElementById('stat-pdf').textContent = s.pdf_exists ? 'ready' : 'not built';
        document.getElementById('stat-pdf').className = s.pdf_exists ? 'ok' : 'pending';

        const links = document.getElementById('download-links');
        links.innerHTML = '';
        if (s.docx_exists) links.innerHTML += `<a class="download" href="/download/docx">Download ${s.docx_name}</a><br>`;
        if (s.pdf_exists) links.innerHTML += `<a class="download" href="/download/pdf">Download ${s.pdf_name}</a>`;

        if (!s.running) { clearInterval(timer); polling = false; }
      }, 1000);
    }
    poll();
  </script>
</body>
</html>
"""

HISTORY_PAGE = """
<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <title>yt-to-book — History</title>
  <style>{{ base_style }}</style>
</head>
<body>
  <h1>yt-to-book</h1>
  <nav><a href="{{ url_for('index') }}">Pipeline</a><a href="{{ url_for('history') }}">History</a></nav>

  <div class="card">
    {% if entries %}
    <table>
      <tr><th>Title</th><th>Source URL</th><th>Videos</th><th>Fetched</th><th>Downloads</th><th></th></tr>
      {% for e in entries %}
      <tr>
        <td>{{ e.title }}</td>
        <td class="muted">{{ e.url }}</td>
        <td>{{ e.video_count }}</td>
        <td class="muted">{{ e.fetched_at }}</td>
        <td>
          {% if e.docx_exists %}<a href="{{ url_for('download_docx_slug', slug=e.slug) }}">DOCX</a>{% endif %}
          {% if e.docx_exists and e.pdf_exists %} · {% endif %}
          {% if e.pdf_exists %}<a href="{{ url_for('download_pdf_slug', slug=e.slug) }}">PDF</a>{% endif %}
          {% if not e.docx_exists and not e.pdf_exists %}<span class="muted">not built</span>{% endif %}
        </td>
        <td>
          <form method="post" action="{{ url_for('use_channel') }}" style="display:inline;">
            <input type="hidden" name="channel_url" value="{{ e.url }}">
            <button type="submit">Re-run</button>
          </form>
        </td>
      </tr>
      {% endfor %}
    </table>
    {% else %}
    <p class="muted">No books built yet.</p>
    {% endif %}
  </div>
</body>
</html>
"""


def all_videos() -> list[dict]:
    if not VIDEOS_PATH.exists():
        return []
    return json.loads(VIDEOS_PATH.read_text())


def selected_ids(videos: list[dict]) -> set[str]:
    """Which fetched videos should actually go into the book. Defaults to all of
    them (so CLI-only use, with no selection ever saved, behaves as before)."""
    all_ids = {v["id"] for v in videos}
    if SELECTED_PATH.exists():
        saved = set(json.loads(SELECTED_PATH.read_text()))
        return saved & all_ids
    return all_ids


def status_payload() -> dict:
    docx, pdf = docx_path(), pdf_path()
    videos = all_videos()
    sel_ids = selected_ids(videos)
    transcript_count = sum(1 for vid in sel_ids if (TRANSCRIPTS_DIR / f"{vid}.txt").exists())
    chapter_count = sum(1 for vid in sel_ids if (CHAPTERS_DIR / f"{vid}.txt").exists())
    with RUN_LOCK:
        running, label, output = RUN_STATE["running"], RUN_STATE["label"], RUN_STATE["output"]
    return {
        "running": running,
        "label": label,
        "output": output,
        "video_count": len(videos),
        "selected_count": len(sel_ids),
        "transcript_count": transcript_count,
        "chapter_count": chapter_count,
        "docx_exists": docx.exists(),
        "pdf_exists": pdf.exists(),
        "docx_name": docx.name,
        "pdf_name": pdf.name,
    }


def render():
    channel_url = get_key(str(ENV_PATH), "YOUTUBE_CHANNEL_URL") or ""
    videos = all_videos()
    sel_ids = selected_ids(videos)
    payload = status_payload()
    return render_template_string(
        PAGE,
        base_style=BASE_STYLE,
        channel_url=channel_url,
        videos=videos,
        selected_ids=sel_ids,
        video_count=payload["video_count"],
        selected_count=payload["selected_count"],
        transcript_count=payload["transcript_count"],
        chapter_count=payload["chapter_count"],
        docx_exists=payload["docx_exists"],
        pdf_exists=payload["pdf_exists"],
        docx_name=payload["docx_name"],
        pdf_name=payload["pdf_name"],
        steps=STEPS,
    )


@app.route("/")
def index():
    return render()


@app.route("/status")
def status():
    return jsonify(status_payload())


@app.route("/start/<script>", methods=["POST"])
def start_step(script):
    if script not in STEP_SCRIPTS:
        return jsonify({"ok": False, "error": "unknown script"}), 400
    label = dict(STEPS)[script]
    ok = start_run(_worker_single, script, label)
    return jsonify({"ok": ok})


@app.route("/start-all", methods=["POST"])
def start_all():
    ok = start_run(_worker_all)
    return jsonify({"ok": ok})


@app.route("/stop", methods=["POST"])
def stop():
    with RUN_LOCK:
        RUN_STATE["stop_requested"] = True
        proc = RUN_STATE["process"]
    if proc and proc.poll() is None:
        proc.terminate()
    return jsonify({"ok": True})


@app.route("/history")
def history():
    entries = json.loads(HISTORY_PATH.read_text()) if HISTORY_PATH.exists() else []
    for e in entries:
        e["docx_exists"] = docx_path(e["slug"]).exists()
        e["pdf_exists"] = pdf_path(e["slug"]).exists()
    return render_template_string(HISTORY_PAGE, base_style=BASE_STYLE, entries=entries)


@app.route("/use-channel", methods=["POST"])
def use_channel():
    channel_url = request.form.get("channel_url", "").strip()
    if channel_url:
        set_key(str(ENV_PATH), "YOUTUBE_CHANNEL_URL", channel_url)
        SELECTED_PATH.unlink(missing_ok=True)
    return redirect(url_for("index"))


@app.route("/set-channel", methods=["POST"])
def set_channel():
    channel_url = request.form.get("channel_url", "").strip()
    if channel_url:
        set_key(str(ENV_PATH), "YOUTUBE_CHANNEL_URL", channel_url)
        # A new channel invalidates any selection made for the previous one.
        SELECTED_PATH.unlink(missing_ok=True)
    return redirect(url_for("index"))


@app.route("/select", methods=["POST"])
def save_selection():
    ids = request.form.getlist("video_id")
    SELECTED_PATH.parent.mkdir(parents=True, exist_ok=True)
    SELECTED_PATH.write_text(json.dumps(ids, indent=2))
    return redirect(url_for("index"))


@app.route("/download/docx")
def download_docx():
    return send_file(docx_path(), as_attachment=True)


@app.route("/download/pdf")
def download_pdf():
    return send_file(pdf_path(), as_attachment=True)


@app.route("/download/docx/<slug>")
def download_docx_slug(slug):
    return send_file(docx_path(slug), as_attachment=True)


@app.route("/download/pdf/<slug>")
def download_pdf_slug(slug):
    return send_file(pdf_path(slug), as_attachment=True)


if __name__ == "__main__":
    app.run(debug=True, port=5050)
