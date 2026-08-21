"""Step 5 — Export the book as a professionally typeset PDF.

Generates a Typst (.typ) document and compiles it with the `typst` CLI.
Typst gives real hyphenation, kerning/ligatures, a native table of
contents with dot leaders and correct page numbers, automatic PDF
bookmarks, and (via the `droplet` package) genuine multi-line drop caps
— all things ReportLab's layout engine can't do well. Install once with
`brew install typst` (or see https://typst.app).
"""
import json
import os
import re
import shutil
import subprocess
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

BASE = Path(__file__).parent
VIDEOS_PATH = BASE / "data" / "videos.json"
CHAPTERS_DIR = BASE / "data" / "chapters"
IMAGES_DIR = BASE / "data" / "images"
OUT_PATH = BASE / "output" / "book.pdf"
TYP_PATH = BASE / "output" / "_book.typ"

BOOK_TITLE = os.getenv("BOOK_TITLE", "Parenting with Dr. Debmita Dutta")
BOOK_SUBTITLE = os.getenv(
    "BOOK_SUBTITLE", "Insights on Raising Calm, Confident, Successful Children"
)
BOOK_BYLINE = os.getenv("BOOK_BYLINE", "Compiled from the YouTube channel of Dr. Debmita Dutta")

FONT = os.getenv("PDF_FONT", "Georgia")
ACCENT = os.getenv("PDF_ACCENT", "#B5533C")
ACCENT_DARK = os.getenv("PDF_ACCENT_DARK", "#7A3229")

# --- Typst markup helpers --------------------------------------------------
TYPST_SPECIAL = re.compile(r"([\\#$_*\[\]<>@`~=+\/-])")


def typst_escape(text: str) -> str:
    return TYPST_SPECIAL.sub(r"\\\1", text)


def markdown_to_typst(text: str) -> str:
    """Convert **bold** / *italic* markdown into Typst's *bold* / _italic_, escaping
    everything else so stray markup-significant characters render literally."""
    parts = re.split(r"(\*\*.+?\*\*|\*.+?\*)", text)
    out = []
    for part in parts:
        if not part:
            continue
        if part.startswith("**") and part.endswith("**"):
            out.append(f"*{typst_escape(part[2:-2])}*")
        elif part.startswith("*") and part.endswith("*"):
            out.append(f"_{typst_escape(part[1:-1])}_")
        else:
            out.append(typst_escape(part))
    return "".join(out)


def parse_chapter(raw: str) -> tuple[str, str]:
    lines = raw.strip().splitlines()
    if lines and lines[0].startswith("#"):
        title = lines[0].lstrip("#").strip()
        body = "\n".join(lines[1:]).strip()
    else:
        title = lines[0].strip() if lines else "Untitled Chapter"
        body = "\n".join(lines[1:]).strip() if len(lines) > 1 else ""
    return title, body


def load_images(video_id: str) -> tuple[float, list[dict]]:
    manifest = IMAGES_DIR / video_id / "images.json"
    if not manifest.exists():
        return 0.0, []
    data = json.loads(manifest.read_text())
    return data.get("duration", 0.0), data.get("images", [])


def compute_placements(num_blocks: int, images: list[dict], duration: float) -> dict[int, list[dict]]:
    """Map each image to a paragraph-block index by matching its proportional position
    in the video's timeline to the same proportional position in the chapter text."""
    placements: dict[int, list[dict]] = {}
    if not images or duration <= 0 or num_blocks == 0:
        return placements
    for img in images:
        proportion = min(max(img["timestamp"] / duration, 0.0), 1.0)
        idx = min(int(round(proportion * num_blocks)), num_blocks - 1)
        placements.setdefault(idx, []).append(img)
    return placements


def figure_typst(video_id: str, img: dict) -> str:
    # TYP_PATH lives in output/, images live in data/images/<id>/ — one level up, then across.
    rel_path = f"../data/images/{video_id}/{img['file']}"
    return f'#figure(image("{rel_path}", width: 78%), caption: [{typst_escape(img["caption"])}])'


def body_to_typst(body: str, video_id: str = "", placements: dict | None = None) -> str:
    """Render chapter body blocks as Typst markup. The first real paragraph gets a
    genuine wrap-around drop cap; ##/**bold-line** blocks become level-2 headings;
    images are interleaved at their computed placement index."""
    placements = placements or {}
    out = []
    first_paragraph_done = False
    blocks = [b.strip() for b in body.split("\n\n") if b.strip()]

    for i, block in enumerate(blocks):
        for img in placements.get(i, []):
            out.append(figure_typst(video_id, img))

        heading_match = re.match(r"^#{2,3}\s+(.*)", block)
        bold_heading_match = re.match(r"^\*\*(.+?)\*\*$", block) if not heading_match else None
        heading_text = heading_match.group(1).strip() if heading_match else (
            bold_heading_match.group(1).strip() if bold_heading_match else None
        )

        if heading_text is not None:
            out.append(f"== {typst_escape(heading_text)}")
            continue

        converted = markdown_to_typst(block)
        if not first_paragraph_done:
            out.append(f"#dropcap(height: 3, gap: 8pt)[{converted}]")
            first_paragraph_done = True
        else:
            out.append(converted)

    for img in placements.get(len(blocks), []):
        out.append(figure_typst(video_id, img))

    return "\n\n".join(out)


PREAMBLE = f"""\
#import "@preview/droplet:0.3.1": dropcap

#let accent = rgb("{ACCENT}")
#let accent-dark = rgb("{ACCENT_DARK}")
#let muted = rgb("#7A7A7A")
#let body-font = "{FONT}"

#set text(font: body-font, size: 11pt, lang: "en", fill: rgb("#1A1A1A"))
#set par(justify: true, leading: 0.75em, first-line-indent: 1.2em)

#show heading.where(level: 1): it => align(center)[
  #text(font: body-font, weight: "bold", size: 24pt, fill: accent-dark)[#it.body]
]
#show heading.where(level: 2): it => block(above: 22pt, below: 8pt)[
  #text(font: body-font, weight: "bold", size: 13.5pt, fill: accent)[#it.body]
]

#let running-header = context {{
  align(center)[
    #text(font: body-font, style: "italic", size: 8pt, fill: muted)[{typst_escape(BOOK_TITLE.upper())}]
    #v(2pt)
    #line(length: 100%, stroke: 0.6pt + accent)
  ]
}}
#let page-footer = context align(center)[
  #text(font: body-font, weight: "bold", size: 9pt, fill: accent)[#counter(page).display()]
]

#set page(
  width: 6in, height: 9in,
  margin: (x: 0.75in, y: 0.75in),
  header: running-header,
  footer: page-footer,
)

// --- Cover ---
#page(header: none, footer: none)[
  #v(2.2in)
  #align(center)[
    #text(font: body-font, weight: "bold", size: 32pt, fill: accent-dark)[{typst_escape(BOOK_TITLE)}]
    #v(10pt)
    #line(length: 22%, stroke: 2pt + accent)
    #v(16pt)
    #text(font: body-font, style: "italic", size: 15pt, fill: muted)[{typst_escape(BOOK_SUBTITLE)}]
    #v(24pt)
    #text(font: body-font, size: 11pt, fill: rgb("#A8A8A8"))[{typst_escape(BOOK_BYLINE)}]
  ]
]

// --- Table of contents ---
#align(center)[
  #text(font: body-font, weight: "bold", size: 22pt, fill: accent-dark)[Contents]
  #v(4pt)
  #line(length: 18%, stroke: 1.4pt + accent)
]
#v(22pt)
#show outline.entry: it => block(below: 12pt)[#it]
#outline(title: none, target: heading.where(level: 1), indent: auto)
#pagebreak(weak: true)
"""


def chapter_block(number: int, video_id: str, title: str, body: str) -> str:
    kicker = f"CHAPTER {number}"
    duration, images = load_images(video_id)
    num_blocks = len([b for b in body.split("\n\n") if b.strip()])
    placements = compute_placements(num_blocks, images, duration)
    return f"""
#pagebreak(weak: true)
#align(center)[
  #text(font: body-font, weight: "bold", size: 13pt, fill: accent, tracking: 0.18em)[{typst_escape(kicker)}]
]
#v(6pt)
= {typst_escape(title)}
#v(4pt)
#align(center)[#line(length: 14%, stroke: 1.6pt + accent)]
#v(18pt)

{body_to_typst(body, video_id, placements)}
"""


def appendix_block(chapters: list[tuple[str, str, str]], videos: dict) -> str:
    lines = [
        '#pagebreak(weak: true)',
        '#align(center)[',
        f'  #text(font: body-font, weight: "bold", size: 22pt, fill: accent-dark)[Appendix: Source Videos]',
        "  #v(4pt)",
        "  #line(length: 18%, stroke: 1.4pt + accent)",
        "]",
        "#v(20pt)",
    ]
    for video_id, title, _ in chapters:
        url = videos.get(video_id, {}).get("url", f"https://www.youtube.com/watch?v={video_id}")
        lines.append(f'#text(weight: "bold", size: 11pt)[{typst_escape(title)}]')
        lines.append(f'#v(1pt)')
        lines.append(f'#text(style: "italic", size: 10pt, fill: muted)[{typst_escape(url)}]')
        lines.append("#v(8pt)")
    return "\n".join(lines)


def build_typst_source(videos: dict, chapter_files: list[Path]) -> str:
    parts = [PREAMBLE]

    chapters = []
    for i, path in enumerate(chapter_files, 1):
        video_id = path.stem
        title, body = parse_chapter(path.read_text(encoding="utf-8"))
        chapters.append((video_id, title, body))
        parts.append(chapter_block(i, video_id, title, body))

    parts.append(appendix_block(chapters, videos))
    return "\n".join(parts)


def main():
    if not VIDEOS_PATH.exists():
        raise SystemExit("data/videos.json not found — run 1_fetch_videos.py first")
    if not shutil.which("typst"):
        raise SystemExit("typst CLI not found — install it first: brew install typst")

    videos = {v["id"]: v for v in json.loads(VIDEOS_PATH.read_text())}
    chapter_files = sorted(CHAPTERS_DIR.glob("*.txt"))
    if not chapter_files:
        raise SystemExit("No chapters found in data/chapters/ — run 3_build_book.py first")

    def sort_key(path: Path):
        return videos.get(path.stem, {}).get("upload_date") or "00000000"

    chapter_files.sort(key=sort_key)

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    TYP_PATH.write_text(build_typst_source(videos, chapter_files), encoding="utf-8")

    result = subprocess.run(
        ["typst", "compile", str(TYP_PATH), str(OUT_PATH)],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise SystemExit(f"typst compile failed:\n{result.stderr}")

    print(f"PDF exported -> {OUT_PATH}  ({len(chapter_files)} chapters, Typst + {FONT})")


if __name__ == "__main__":
    main()
