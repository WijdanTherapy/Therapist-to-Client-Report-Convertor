import streamlit as st
import pdfplumber
import fitz  # PyMuPDF
from anthropic import Anthropic
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import cm, mm
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
    HRFlowable, Image as RLImage, KeepTogether
)
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_JUSTIFY
from reportlab.graphics.shapes import Drawing, Rect, String
from reportlab.graphics import renderPDF
from reportlab.graphics.charts.barcharts import HorizontalBarChart
import io
import base64
import re
import os
import tempfile
from datetime import datetime
from PIL import Image as PILImage

# ─── Page config ──────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Wijdan – Client Friendly Report",
    page_icon="🌿",
    layout="centered",
)

# ─── Styling ───────────────────────────────────────────────────────────────────
st.markdown("""
<style>
  .main { background: #f7f9f6; }
  .stButton > button {
    background: #4a7c59; color: white;
    border-radius: 8px; border: none;
    padding: 0.6rem 2rem; font-size: 1rem;
  }
  .stButton > button:hover { background: #3a6047; }
  h1 { color: #2d4a38; }
  .info-box {
    background: #e8f0ea; border-left: 4px solid #4a7c59;
    padding: 1rem 1.2rem; border-radius: 6px; margin-bottom: 1rem;
  }
</style>
""", unsafe_allow_html=True)

# ─── Header ───────────────────────────────────────────────────────────────────
LOGO_PATH = os.path.join(os.path.dirname(__file__), "logo.png")

col1, col2 = st.columns([1, 4])
with col1:
    if os.path.exists(LOGO_PATH):
        st.image(LOGO_PATH, width=90)
with col2:
    st.markdown("## Wijdan — Client Friendly Report")
    st.caption("Transform your therapist's assessment into a warm, easy-to-understand personal report")

st.markdown("---")

# ─── Helpers ──────────────────────────────────────────────────────────────────

def extract_pdf_text(uploaded_file) -> str:
    """Extract all text from uploaded PDF."""
    bytes_data = uploaded_file.read()
    with pdfplumber.open(io.BytesIO(bytes_data)) as pdf:
        pages = []
        for page in pdf.pages:
            t = page.extract_text()
            if t:
                pages.append(t)
    return "\n\n".join(pages)


def extract_logo_from_pdf(uploaded_file) -> bytes | None:
    """Try to extract the embedded logo from the PDF (first image on page 1)."""
    uploaded_file.seek(0)
    bytes_data = uploaded_file.read()
    doc = fitz.open(stream=bytes_data, filetype="pdf")
    page = doc[0]
    images = page.get_images()
    for img_info in images:
        xref = img_info[0]
        base = doc.extract_image(xref)
        img_bytes = base["image"]
        # must be reasonably large (not a tiny icon)
        if len(img_bytes) > 5000:
            return img_bytes
    return None


def extract_pdf_metadata(raw_text: str) -> dict:
    """Pull basic metadata from raw text using simple heuristics."""
    meta = {}
    for line in raw_text.split("\n")[:40]:
        if "client" in line.lower() and ":" in line.lower():
            meta["client"] = line.split(":", 1)[-1].strip()
        if "assessment" in line.lower() and ":" in line.lower():
            meta["assessment"] = line.split(":", 1)[-1].strip()
        if "date" in line.lower() and ":" in line.lower():
            meta["date"] = line.split(":", 1)[-1].strip()
        if "score" in line.lower() and ("total" in line.lower() or "/") :
            meta["score_line"] = line.strip()
    return meta


def call_claude_for_client_report(raw_text: str) -> str:
    """Send therapist text to Claude and get a client-friendly interpretation."""
    client = Anthropic()

    system = """You are a compassionate psychologist writing a **personal feedback letter** for a client.

Your job: transform a clinical/therapist assessment report into a warm, empowering, client-friendly document.

STRICT RULES:
1. NO clinical diagnoses, no diagnostic labels (e.g., do NOT say "Major Depressive Disorder", "MDD", "Psychopathic Deviate", "Schizophrenia scale", etc.).
2. NO treatment recommendations (no CBT, no medication, no therapy modalities).
3. NO risk formulations or clinical risk language.
4. DO keep all scores, numbers, and scale names — just explain them in plain language.
5. Write in second person ("you", "your") — warm, encouraging, non-judgmental.
6. Preserve the structure of the original (same sections, same order).
7. Convert clinical jargon: e.g., "Hypochondriasis scale" → "how much you focus on your physical health".
8. For each score/domain — briefly explain what it measures, what the score means for the person's daily life, and 2-3 practical, self-help suggestions (NOT therapy — lifestyle, mindset, habits).
9. If suicidal ideation or severe risk items are mentioned — replace with a warm message like: "Some of your responses suggest you may be going through a particularly hard time emotionally. You don't have to carry that alone — talking to someone you trust can make a real difference."
10. End with a warm, hopeful closing paragraph.
11. Output ONLY the report content (no preamble like "Here is the report:"). Use clear section headings.
12. Use plain language — imagine writing to a thoughtful 18-year-old with no psychology background.

Format your output as structured sections with headings like:
## 👋 A Note to You
## 📊 Your Results at a Glance
## 🔍 What Each Score Means for You
## 💡 Tips & Suggestions for You
## 🌱 Moving Forward

Adapt sections to match the original report's structure."""

    user = f"""Here is the therapist's clinical assessment report. Please transform it into a client-friendly personal feedback letter following the rules above.

CLINICAL REPORT:
{raw_text}"""

    message = client.messages.create(
        model="claude-opus-4-5",
        max_tokens=4000,
        system=system,
        messages=[{"role": "user", "content": user}]
    )
    return message.content[0].text


# ─── PDF GENERATION ───────────────────────────────────────────────────────────

# Brand colours (from Wijdan logo / docs)
DARK_GREEN = colors.HexColor("#2d4a38")
MID_GREEN  = colors.HexColor("#4a7c59")
LIGHT_GREEN= colors.HexColor("#a8c8a0")
BG_GREEN   = colors.HexColor("#e8f0ea")
GREY_TEXT  = colors.HexColor("#555555")
BLACK      = colors.black
WHITE      = colors.white


def build_styles():
    styles = getSampleStyleSheet()

    styles.add(ParagraphStyle(
        "ClientTitle",
        fontName="Helvetica-Bold",
        fontSize=22,
        textColor=DARK_GREEN,
        alignment=TA_CENTER,
        spaceAfter=4,
    ))
    styles.add(ParagraphStyle(
        "ClientSubtitle",
        fontName="Helvetica-Oblique",
        fontSize=11,
        textColor=MID_GREEN,
        alignment=TA_CENTER,
        spaceAfter=2,
    ))
    styles.add(ParagraphStyle(
        "ClientMeta",
        fontName="Helvetica",
        fontSize=9,
        textColor=GREY_TEXT,
        alignment=TA_CENTER,
        spaceAfter=12,
    ))
    styles.add(ParagraphStyle(
        "SectionHeading",
        fontName="Helvetica-Bold",
        fontSize=13,
        textColor=WHITE,
        backColor=MID_GREEN,
        alignment=TA_LEFT,
        spaceBefore=14,
        spaceAfter=6,
        leftIndent=-12,
        rightIndent=-12,
        borderPadding=(6, 12, 6, 12),
    ))
    styles.add(ParagraphStyle(
        "BodyText2",
        fontName="Helvetica",
        fontSize=10,
        textColor=colors.HexColor("#333333"),
        leading=16,
        alignment=TA_JUSTIFY,
        spaceAfter=8,
    ))
    styles.add(ParagraphStyle(
        "BulletItem",
        fontName="Helvetica",
        fontSize=10,
        textColor=colors.HexColor("#333333"),
        leading=15,
        leftIndent=14,
        spaceAfter=4,
    ))
    styles.add(ParagraphStyle(
        "FooterText",
        fontName="Helvetica-Oblique",
        fontSize=8,
        textColor=GREY_TEXT,
        alignment=TA_CENTER,
    ))
    return styles


def markdown_to_flowables(md_text: str, styles) -> list:
    """Convert the Claude markdown output into ReportLab flowables."""
    flowables = []
    lines = md_text.split("\n")
    i = 0
    while i < len(lines):
        line = lines[i].rstrip()

        # Section heading (## ...)
        if line.startswith("## "):
            heading = line[3:].strip()
            flowables.append(Spacer(1, 6))
            # Green banner
            data = [[Paragraph(heading, styles["SectionHeading"])]]
            t = Table(data, colWidths=[17*cm])
            t.setStyle(TableStyle([
                ("BACKGROUND", (0,0), (-1,-1), MID_GREEN),
                ("LEFTPADDING", (0,0), (-1,-1), 12),
                ("RIGHTPADDING", (0,0), (-1,-1), 12),
                ("TOPPADDING", (0,0), (-1,-1), 6),
                ("BOTTOMPADDING", (0,0), (-1,-1), 6),
                ("ROUNDEDCORNERS", [6,6,6,6]),
            ]))
            flowables.append(t)

        # Sub-heading (### ...)
        elif line.startswith("### "):
            heading = line[4:].strip()
            flowables.append(Spacer(1, 4))
            p = Paragraph(f"<b><font color='#{DARK_GREEN.hexval()[2:]}' size='11'>{heading}</font></b>", styles["BodyText2"])
            flowables.append(p)

        # Bullet point
        elif line.startswith("- ") or line.startswith("* "):
            text = line[2:].strip()
            text = _inline_md(text)
            p = Paragraph(f"<font color='#{MID_GREEN.hexval()[2:]}'>●</font>  {text}", styles["BulletItem"])
            flowables.append(p)

        # Numbered list
        elif re.match(r"^\d+\.", line):
            text = re.sub(r"^\d+\.\s*", "", line).strip()
            text = _inline_md(text)
            p = Paragraph(f"<font color='#{MID_GREEN.hexval()[2:]}'>▸</font>  {text}", styles["BulletItem"])
            flowables.append(p)

        # Horizontal rule
        elif line.startswith("---"):
            flowables.append(HRFlowable(width="100%", thickness=1, color=LIGHT_GREEN, spaceAfter=6))

        # Empty line → spacer
        elif line.strip() == "":
            flowables.append(Spacer(1, 4))

        # Normal paragraph
        else:
            text = _inline_md(line)
            p = Paragraph(text, styles["BodyText2"])
            flowables.append(p)

        i += 1
    return flowables


def _inline_md(text: str) -> str:
    """Convert inline **bold** and *italic* markdown to ReportLab XML."""
    # Bold
    text = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", text)
    # Italic
    text = re.sub(r"\*(.+?)\*", r"<i>\1</i>", text)
    # Escape & that aren't already entities
    text = re.sub(r"&(?!amp;|lt;|gt;|quot;|apos;)", "&amp;", text)
    return text


def generate_client_pdf(
    client_text: str,
    original_text: str,
    logo_bytes: bytes | None,
    meta: dict,
) -> bytes:
    """Build and return the client-friendly PDF as bytes."""

    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=A4,
        leftMargin=2.5*cm,
        rightMargin=2.5*cm,
        topMargin=2*cm,
        bottomMargin=2.5*cm,
    )
    styles = build_styles()
    story = []

    # ── Logo ──────────────────────────────────────────────────────────────
    logo_img = None
    if logo_bytes:
        try:
            pil = PILImage.open(io.BytesIO(logo_bytes)).convert("RGBA")
            tmp = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
            pil.save(tmp.name)
            logo_img = RLImage(tmp.name, width=3.5*cm, height=3*cm)
            logo_img.hAlign = "CENTER"
        except Exception:
            logo_img = None

    # Fallback: use local logo.png
    if logo_img is None and os.path.exists(LOGO_PATH):
        logo_img = RLImage(LOGO_PATH, width=3.5*cm, height=3*cm)
        logo_img.hAlign = "CENTER"

    if logo_img:
        story.append(logo_img)
        story.append(Spacer(1, 6))

    # ── Title block ───────────────────────────────────────────────────────
    assess = meta.get("assessment", "Psychological Assessment")
    story.append(Paragraph("Personal Wellbeing Report", styles["ClientTitle"]))
    story.append(Paragraph(assess, styles["ClientSubtitle"]))

    date_str = meta.get("date", datetime.now().strftime("%B %d, %Y"))
    client_name = meta.get("client", "")
    meta_line = f"Prepared for: <b>{client_name}</b>  &nbsp;|&nbsp;  Date: {date_str}" if client_name else f"Date: {date_str}"
    story.append(Paragraph(meta_line, styles["ClientMeta"]))

    story.append(HRFlowable(width="100%", thickness=2, color=MID_GREEN, spaceBefore=4, spaceAfter=12))

    # ── Client-friendly content ───────────────────────────────────────────
    flowables = markdown_to_flowables(client_text, styles)
    story.extend(flowables)

    story.append(Spacer(1, 16))
    story.append(HRFlowable(width="100%", thickness=1, color=LIGHT_GREEN))
    story.append(Spacer(1, 6))

    # ── Footer ─────────────────────────────────────────────────────────────
    footer_text = (
        "This personal feedback report is prepared by Wijdan — Unleash Inner Peace. "
        "It is intended to help you understand your assessment results in an accessible way. "
        "For clinical interpretation, please consult your treating clinician."
    )
    story.append(Paragraph(footer_text, styles["FooterText"]))

    doc.build(story)
    buf.seek(0)
    return buf.read()


# ─── Main UI ──────────────────────────────────────────────────────────────────

st.markdown("### 📄 Upload the Therapist Assessment PDF")

st.markdown("""
<div class='info-box'>
Upload the clinical PDF generated by your assessment app. The system will:
<ul>
  <li>Keep all scores, tables, and graphs</li>
  <li>Rewrite the interpretation in warm, plain language</li>
  <li>Add personalised self-help suggestions</li>
  <li>Preserve the Wijdan branding and layout</li>
</ul>
</div>
""", unsafe_allow_html=True)

uploaded_file = st.file_uploader(
    "Choose a PDF file",
    type=["pdf"],
    help="Upload the therapist's clinical report PDF"
)

if uploaded_file:
    st.success(f"✅ Loaded: **{uploaded_file.name}**")

    with st.expander("👁️ Preview extracted text (first 800 chars)"):
        raw = extract_pdf_text(uploaded_file)
        st.text(raw[:800] + "…" if len(raw) > 800 else raw)

    uploaded_file.seek(0)
    meta = extract_pdf_metadata(raw)
    if meta.get("client"):
        st.info(f"🧑 Client detected: **{meta['client']}** | Assessment: {meta.get('assessment','—')}")

    st.markdown("---")
    if st.button("🌿 Generate Client-Friendly Report", use_container_width=True):
        with st.spinner("Reading the assessment and crafting your personal report… this takes ~30 seconds"):
            try:
                # 1. Extract logo from PDF
                uploaded_file.seek(0)
                logo_bytes = extract_logo_from_pdf(uploaded_file)

                # 2. Call Claude
                uploaded_file.seek(0)
                raw_text = extract_pdf_text(uploaded_file)
                client_text = call_claude_for_client_report(raw_text)

                # 3. Generate PDF
                pdf_bytes = generate_client_pdf(client_text, raw_text, logo_bytes, meta)

                st.success("✨ Your personal report is ready!")

                # Show preview of the text
                with st.expander("📖 Preview the client-friendly text"):
                    st.markdown(client_text)

                # Download button
                client_name_slug = meta.get("client", "client").replace(" ", "_").lower()
                assess_slug = meta.get("assessment", "report").replace(" ", "_").replace("(", "").replace(")", "").lower()
                filename = f"personal_report_{client_name_slug}_{assess_slug}.pdf"

                st.download_button(
                    label="⬇️ Download Personal Report PDF",
                    data=pdf_bytes,
                    file_name=filename,
                    mime="application/pdf",
                    use_container_width=True,
                )

            except Exception as e:
                st.error(f"Something went wrong: {e}")
                st.exception(e)

else:
    st.markdown("""
    <div style='text-align:center; padding: 3rem; color: #888;'>
    📂 Upload a clinical assessment PDF above to get started
    </div>
    """, unsafe_allow_html=True)
