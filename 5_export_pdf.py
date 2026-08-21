"""Step 5 — Export the book as a professionally typeset PDF.

Cover page, dot-leader table of contents with real page numbers, chapter
title pages, justified serif body text, running header/footer, PDF
bookmarks. Uses ReportLab (Platypus + multiBuild for the TOC pass).
"""
import json
import os
import re
from pathlib import Path

from dotenv import load_dotenv
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY
from reportlab.lib.pagesizes import inch
from reportlab.lib.styles import ParagraphStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.pdfmetrics import registerFontFamily
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    BaseDocTemplate,
    Frame,
    HRFlowable,
    NextPageTemplate,
    PageBreak,
    PageTemplate,
    Paragraph,
    Spacer,
)
from reportlab.platypus.tableofcontents import TableOfContents

load_dotenv()

BASE = Path(__file__).parent
VIDEOS_PATH = BASE / "data" / "videos.json"
CHAPTERS_DIR = BASE / "data" / "chapters"
OUT_PATH = BASE / "output" / "book.pdf"

BOOK_TITLE = os.getenv("BOOK_TITLE", "Parenting with Dr. Debmita Dutta")
BOOK_SUBTITLE = os.getenv(
    "BOOK_SUBTITLE", "Insights on Raising Calm, Confident, Successful Children"
)
BOOK_BYLINE = os.getenv("BOOK_BYLINE", "Compiled from the YouTube channel of Dr. Debmita Dutta")

PAGE_SIZE = (6 * inch, 9 * inch)
MARGIN = 0.75 * inch

# --- Fonts -------------------------------------------------------------
FONT_DIR = Path("/System/Library/Fonts/Supplemental")
FONT_FILES = {
    "Georgia": "Georgia.ttf",
    "Georgia-Bold": "Georgia Bold.ttf",
    "Georgia-Italic": "Georgia Italic.ttf",
    "Georgia-BoldItalic": "Georgia Bold Italic.ttf",
}


def register_fonts():
    if all((FONT_DIR / f).exists() for f in FONT_FILES.values()):
        for name, filename in FONT_FILES.items():
            pdfmetrics.registerFont(TTFont(name, str(FONT_DIR / filename)))
        registerFontFamily(
            "Georgia",
            normal="Georgia",
            bold="Georgia-Bold",
            italic="Georgia-Italic",
            boldItalic="Georgia-BoldItalic",
        )
        return "Georgia", "Georgia-Bold", "Georgia-Italic", "Georgia-BoldItalic"
    # Fallback for machines without the macOS Supplemental fonts installed
    return "Times-Roman", "Times-Bold", "Times-Italic", "Times-BoldItalic"


FONT, FONT_BOLD, FONT_ITALIC, FONT_BOLD_ITALIC = register_fonts()

# --- Color palette ---------------------------------------------------------
# Override via .env if you want a different accent (e.g. PDF_ACCENT=#1B5E56)
ACCENT_HEX = os.getenv("PDF_ACCENT", "#B5533C")  # terracotta — chapter numerals, subheads, rules
ACCENT_DARK_HEX = os.getenv("PDF_ACCENT_DARK", "#7A3229")  # cover title, chapter titles
ACCENT = colors.HexColor(ACCENT_HEX)
ACCENT_DARK = colors.HexColor(ACCENT_DARK_HEX)
TEXT = colors.HexColor("#1A1A1A")
MUTED = colors.HexColor("#7A7A7A")
MUTED_LIGHT = colors.HexColor("#A8A8A8")

# --- Styles --------------------------------------------------------------
COVER_TITLE = ParagraphStyle(
    "CoverTitle",
    fontName=FONT_BOLD,
    fontSize=32,
    leading=38,
    alignment=TA_CENTER,
    textColor=ACCENT_DARK,
    spaceAfter=16,
)
COVER_SUBTITLE = ParagraphStyle(
    "CoverSubtitle",
    fontName=FONT_ITALIC,
    fontSize=15,
    leading=20,
    alignment=TA_CENTER,
    textColor=MUTED,
    spaceAfter=28,
)
COVER_BYLINE = ParagraphStyle(
    "CoverByline", fontName=FONT, fontSize=11, alignment=TA_CENTER, textColor=MUTED_LIGHT
)
TOC_HEADING = ParagraphStyle(
    "TOCHeading",
    fontName=FONT_BOLD,
    fontSize=22,
    alignment=TA_CENTER,
    textColor=ACCENT_DARK,
    spaceAfter=6,
)
CHAPTER_NUM = ParagraphStyle(
    "ChapterNum",
    fontName=FONT_BOLD,
    fontSize=13,
    alignment=TA_CENTER,
    textColor=ACCENT,
    spaceAfter=8,
)
CHAPTER_TITLE = ParagraphStyle(
    "ChapterTitleTOC",
    fontName=FONT_BOLD,
    fontSize=24,
    leading=29,
    alignment=TA_CENTER,
    textColor=ACCENT_DARK,
    spaceAfter=14,
)
APPENDIX_HEADING = ParagraphStyle(
    "AppendixHeading", fontName=FONT_BOLD, fontSize=22, alignment=TA_CENTER, textColor=ACCENT_DARK, spaceAfter=6
)
BODY = ParagraphStyle(
    "Body",
    fontName=FONT,
    fontSize=11,
    leading=17,
    alignment=TA_JUSTIFY,
    textColor=TEXT,
    spaceAfter=10,
    firstLineIndent=18,
)
SUBHEAD = ParagraphStyle(
    "SubHead", fontName=FONT_BOLD, fontSize=13.5, spaceBefore=22, spaceAfter=8, textColor=ACCENT
)
APPENDIX_TITLE = ParagraphStyle(
    "AppendixTitle", fontName=FONT_BOLD, fontSize=11, textColor=TEXT, spaceBefore=8, spaceAfter=2
)
APPENDIX_URL = ParagraphStyle("AppendixURL", fontName=FONT_ITALIC, fontSize=10, textColor=MUTED, spaceAfter=4)

TOC_ENTRY = ParagraphStyle(
    "TOCEntry", fontName=FONT, fontSize=12, leading=22, leftIndent=0, textColor=TEXT, dotColor=MUTED_LIGHT
)


def xml_escape(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def markdown_inline(text: str) -> str:
    text = xml_escape(text)
    text = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", text)
    text = re.sub(r"(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)", r"<i>\1</i>", text)
    return text


def with_drop_cap(text: str) -> str:
    if not text:
        return text
    first, rest = text[0], text[1:]
    return f'<font face="{FONT_BOLD}" size="30" color="{ACCENT_HEX}">{first}</font>{rest}'


def letter_spaced(text: str, sep: str = " ") -> str:
    return sep.join(text)


def parse_chapter(raw: str) -> tuple[str, str]:
    lines = raw.strip().splitlines()
    if lines and lines[0].startswith("#"):
        title = lines[0].lstrip("#").strip()
        body = "\n".join(lines[1:]).strip()
    else:
        title = lines[0].strip() if lines else "Untitled Chapter"
        body = "\n".join(lines[1:]).strip() if len(lines) > 1 else ""
    return title, body


def body_flowables(body: str) -> list:
    flowables = []
    first_paragraph_done = False
    for block in body.split("\n\n"):
        block = block.strip()
        if not block:
            continue
        heading_match = re.match(r"^#{2,3}\s+(.*)", block)
        # Local models tend to emit "**Subheading**" rather than "## Subheading" — treat a
        # block that's a single bold-wrapped line the same way as a markdown heading.
        bold_heading_match = re.match(r"^\*\*(.+?)\*\*$", block) if not heading_match else None
        if heading_match:
            flowables.append(Paragraph(markdown_inline(heading_match.group(1).strip()), SUBHEAD))
            continue
        if bold_heading_match:
            flowables.append(Paragraph(markdown_inline(bold_heading_match.group(1).strip()), SUBHEAD))
            continue

        converted = markdown_inline(block)
        if not first_paragraph_done:
            converted = with_drop_cap(converted)
            first_paragraph_done = True
        flowables.append(Paragraph(converted, BODY))
    return flowables


class BookDocTemplate(BaseDocTemplate):
    def afterFlowable(self, flowable):
        if isinstance(flowable, Paragraph) and flowable.style.name == "ChapterTitleTOC":
            text = flowable.getPlainText()
            self.notify("TOCEntry", (0, text, self.page))
            key = "ch-" + re.sub(r"[^a-z0-9]+", "-", text.lower())[:60]
            self.canv.bookmarkPage(key)
            self.canv.addOutlineEntry(text, key, level=0, closed=False)


def draw_content_furniture(canv, doc):
    canv.saveState()
    canv.setFont(FONT_ITALIC, 8)
    canv.setFillColor(MUTED)
    canv.drawCentredString(PAGE_SIZE[0] / 2, PAGE_SIZE[1] - 0.5 * inch, BOOK_TITLE.upper())
    canv.setStrokeColor(ACCENT)
    canv.setLineWidth(0.7)
    canv.line(MARGIN, PAGE_SIZE[1] - 0.58 * inch, PAGE_SIZE[0] - MARGIN, PAGE_SIZE[1] - 0.58 * inch)

    canv.setFont(FONT_BOLD, 9)
    canv.setFillColor(ACCENT)
    canv.drawCentredString(PAGE_SIZE[0] / 2, 0.45 * inch, str(canv.getPageNumber()))
    canv.restoreState()


def draw_cover_furniture(canv, doc):
    canv.saveState()
    canv.setStrokeColor(ACCENT)
    canv.setLineWidth(2)
    canv.line(PAGE_SIZE[0] / 2 - 0.9 * inch, PAGE_SIZE[1] - 2.55 * inch, PAGE_SIZE[0] / 2 + 0.9 * inch, PAGE_SIZE[1] - 2.55 * inch)
    canv.restoreState()


def build_story(videos: dict, chapter_files: list[Path]) -> list:
    story = []

    # --- Cover ---
    story.append(Spacer(1, 2.2 * inch))
    story.append(Paragraph(xml_escape(BOOK_TITLE), COVER_TITLE))
    story.append(Paragraph(xml_escape(BOOK_SUBTITLE), COVER_SUBTITLE))
    story.append(Paragraph(xml_escape(BOOK_BYLINE), COVER_BYLINE))

    story.append(NextPageTemplate("Content"))
    story.append(PageBreak())

    # --- Table of contents ---
    story.append(Paragraph("Contents", TOC_HEADING))
    story.append(HRFlowable(width="18%", thickness=1.4, color=ACCENT, spaceAfter=22, hAlign="CENTER"))
    toc = TableOfContents()
    toc.levelStyles = [TOC_ENTRY]
    toc.dotsMinLevel = 0
    story.append(toc)
    story.append(PageBreak())

    # --- Chapters ---
    chapters = []
    for i, path in enumerate(chapter_files, 1):
        video_id = path.stem
        title, body = parse_chapter(path.read_text(encoding="utf-8"))
        chapters.append((video_id, title, body))

        story.append(Paragraph(letter_spaced(f"CHAPTER {i}"), CHAPTER_NUM))
        story.append(Paragraph(xml_escape(title), CHAPTER_TITLE))
        story.append(HRFlowable(width="14%", thickness=1.6, color=ACCENT, spaceAfter=22, hAlign="CENTER"))
        story.extend(body_flowables(body))
        story.append(PageBreak())

    # --- Appendix ---
    story.append(Paragraph("Appendix: Source Videos", APPENDIX_HEADING))
    story.append(HRFlowable(width="18%", thickness=1.4, color=ACCENT, spaceAfter=20, hAlign="CENTER"))
    for video_id, title, _ in chapters:
        url = videos.get(video_id, {}).get("url", f"https://www.youtube.com/watch?v={video_id}")
        story.append(Paragraph(xml_escape(title), APPENDIX_TITLE))
        story.append(Paragraph(xml_escape(url), APPENDIX_URL))

    return story


def main():
    if not VIDEOS_PATH.exists():
        raise SystemExit("data/videos.json not found — run 1_fetch_videos.py first")

    videos = {v["id"]: v for v in json.loads(VIDEOS_PATH.read_text())}
    chapter_files = sorted(CHAPTERS_DIR.glob("*.txt"))
    if not chapter_files:
        raise SystemExit("No chapters found in data/chapters/ — run 3_build_book.py first")

    def sort_key(path: Path):
        return videos.get(path.stem, {}).get("upload_date") or "00000000"

    chapter_files.sort(key=sort_key)

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)

    doc = BookDocTemplate(
        str(OUT_PATH),
        pagesize=PAGE_SIZE,
        leftMargin=MARGIN,
        rightMargin=MARGIN,
        topMargin=MARGIN,
        bottomMargin=MARGIN,
        title=BOOK_TITLE,
    )

    content_frame = Frame(MARGIN, MARGIN, PAGE_SIZE[0] - 2 * MARGIN, PAGE_SIZE[1] - 2 * MARGIN, id="content")
    cover_frame = Frame(MARGIN, MARGIN, PAGE_SIZE[0] - 2 * MARGIN, PAGE_SIZE[1] - 2 * MARGIN, id="cover")

    doc.addPageTemplates(
        [
            PageTemplate(id="Cover", frames=[cover_frame], onPage=draw_cover_furniture),
            PageTemplate(id="Content", frames=[content_frame], onPage=draw_content_furniture),
        ]
    )

    story = build_story(videos, chapter_files)
    doc.multiBuild(story)

    print(f"PDF exported -> {OUT_PATH}  ({len(chapter_files)} chapters, font: {FONT})")


if __name__ == "__main__":
    main()
