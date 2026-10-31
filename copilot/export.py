"""User-initiated exports; XML-escape every untrusted PDF field."""

from io import BytesIO
from html import escape
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
from copilot.models import Review


def review_pdf(review: Review) -> bytes:
    stream = BytesIO()
    styles = getSampleStyleSheet()
    styles["Heading2"].keepWithNext = True
    story = []

    def paragraph(value, style="BodyText"):
        # Paragraph's markup parser must never receive raw source or model output.
        text = escape(str(value)).replace("\n", "<br/>")
        story.append(Paragraph(text, styles[style]))
        story.append(Spacer(1, 7))

    paragraph("AI PR Review Copilot", "Title")
    paragraph(f"{review.id} | {review.filename} | {review.created_at}")
    paragraph(
        "Automated review assistance. Static findings confirm rule matches, not exploitable "
        "vulnerabilities. AI findings and fixes require human verification."
    )
    paragraph(review.summary)
    for tool, status in review.status.items():
        paragraph(f"{tool}: {status}")
    if review.ai_summary:
        paragraph("AI summary - unverified", "Heading2")
        paragraph(review.ai_summary)
    for finding in review.findings:
        paragraph(f"{finding.severity.upper()} | {finding.title}", "Heading2")
        paragraph(
            f"{finding.source} / {finding.rule} | lines {finding.line_start}-{finding.line_end}"
        )
        for label, value in [
            ("Evidence", finding.evidence),
            ("Reason", finding.explanation),
            ("Impact", finding.impact),
            ("Suggested fix", finding.suggested_fix),
        ]:
            paragraph(f"{label}: {value}")

    def footer(canvas, doc):
        canvas.setFont("Helvetica", 8)
        canvas.setFillColor(colors.HexColor("#667085"))
        canvas.drawString(
            40,
            25,
            "Generated review export - may contain source evidence. Handle accordingly.",
        )
        canvas.drawRightString(550, 25, str(doc.page))

    SimpleDocTemplate(
        stream, leftMargin=40, rightMargin=40, topMargin=40, bottomMargin=45
    ).build(story, onFirstPage=footer, onLaterPages=footer)
    return stream.getvalue()
