"""Step 4 — Combine chapters into a single DOCX book."""
import json
import re
from pathlib import Path

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.shared import Pt

BASE = Path(__file__).parent
VIDEOS_PATH = BASE / "data" / "videos.json"
CHAPTERS_DIR = BASE / "data" / "chapters"
OUT_PATH = BASE / "output" / "book.docx"


def parse_chapter(text: str) -> tuple[str, str]:
    lines = text.strip().splitlines()
    if lines and lines[0].startswith("#"):
        title = lines[0].lstrip("#").strip()
        body = "\n".join(lines[1:]).strip()
    else:
        title = lines[0].strip() if lines else "Untitled Chapter"
        body = "\n".join(lines[1:]).strip() if len(lines) > 1 else ""
    return title, body


def add_markdown_paragraph(doc: Document, text: str):
    """Add a paragraph, converting **bold** / *italic* markers into real run formatting."""
    p = doc.add_paragraph()
    for token in re.split(r"(\*\*.+?\*\*|\*.+?\*)", text):
        if not token:
            continue
        if token.startswith("**") and token.endswith("**"):
            p.add_run(token[2:-2]).bold = True
        elif token.startswith("*") and token.endswith("*"):
            p.add_run(token[1:-1]).italic = True
        else:
            p.add_run(token)
    return p


def add_body_paragraphs(doc: Document, body: str):
    for block in body.split("\n\n"):
        block = block.strip()
        if not block:
            continue
        heading_match = re.match(r"^#{2,3}\s+(.*)", block)
        # Local models tend to emit "**Subheading**" rather than "## Subheading" — treat a
        # block that's a single bold-wrapped line the same way as a markdown heading.
        bold_heading_match = re.match(r"^\*\*(.+?)\*\*$", block) if not heading_match else None
        if heading_match:
            doc.add_heading(heading_match.group(1).strip(), level=2)
        elif bold_heading_match:
            doc.add_heading(bold_heading_match.group(1).strip(), level=2)
        else:
            add_markdown_paragraph(doc, block)


def main():
    if not VIDEOS_PATH.exists():
        raise SystemExit("data/videos.json not found — run 1_fetch_videos.py first")

    videos = {v["id"]: v for v in json.loads(VIDEOS_PATH.read_text())}
    chapter_files = sorted(CHAPTERS_DIR.glob("*.txt"))

    if not chapter_files:
        raise SystemExit("No chapters found in data/chapters/ — run 3_build_book.py first")

    def sort_key(path: Path):
        v = videos.get(path.stem, {})
        return v.get("upload_date") or "00000000"

    chapter_files.sort(key=sort_key)

    doc = Document()

    # Cover page
    title_p = doc.add_paragraph()
    title_p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = title_p.add_run("The Book")
    run.font.size = Pt(36)
    run.bold = True
    doc.add_page_break()

    # Table of contents (chapter titles only — generated after we parse chapters)
    toc_heading = doc.add_heading("Table of Contents", level=1)
    doc.add_page_break()

    chapters = []
    for path in chapter_files:
        video_id = path.stem
        text = path.read_text(encoding="utf-8")
        title, body = parse_chapter(text)
        chapters.append((video_id, title, body))

    for video_id, title, body in chapters:
        doc.add_heading(title, level=1)
        add_body_paragraphs(doc, body)
        doc.add_page_break()

    # Appendix of video URLs
    doc.add_heading("Appendix: Source Videos", level=1)
    for video_id, title, _ in chapters:
        url = videos.get(video_id, {}).get("url", f"https://www.youtube.com/watch?v={video_id}")
        p = doc.add_paragraph()
        p.add_run(f"{title}").bold = True
        doc.add_paragraph(url)

    # Fill in TOC now that we know chapter titles
    toc_paragraphs = [f"{i+1}. {title}" for i, (_, title, _) in enumerate(chapters)]
    for line in reversed(toc_paragraphs):
        toc_heading._p.addnext(doc.add_paragraph(line)._p)

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    doc.save(OUT_PATH)
    print(f"Book exported -> {OUT_PATH}  ({len(chapters)} chapters)")


if __name__ == "__main__":
    main()
