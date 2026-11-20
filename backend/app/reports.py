from io import BytesIO
from xml.sax.saxutils import escape

from docx import Document
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer


MIME = {"markdown": ("text/markdown", "md"), "docx": (
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document", "docx"),
    "pdf": ("application/pdf", "pdf")}


def source_label(source):
    meta = source["metadata"]
    url = "https://doi.org/" + source["doi"] if source.get("doi") else meta.get("url")
    location = " · ".join(filter(None, [source["section"], f"p. {source['page']}" if source["page"] else "",
                                        source["anchor"].get("xml_path", ""), source["access"]]))
    authors = ", ".join(filter(None, meta.get("authors", [])))
    return " · ".join(filter(None, [source["title"], authors, str(meta.get("year") or ""), meta.get("journal"),
                                   location, url]))


def render(title, result, output_type):
    claims = result.get("claims", [])
    def cited(item):
        sources = item.get("supporting_evidence", [item["evidence"]])
        return item["text"], " | ".join(dict.fromkeys(source_label(source) for source in sources))

    sections = [
        ("Model-checked synthesis", [cited(item) for item in claims if item["type"] == "model_checked_synthesis"]),
        ("Direct evidence", [cited(item) for item in claims if item["type"] != "model_checked_synthesis"]),
        ("Evidence gaps", [(gap, "") for gap in result.get("gaps", [])]),
    ]
    sections = [(heading, items) for heading, items in sections if items]
    comparative = []
    for metric, values in result.get("comparisons", {}).items():
        for group in values["matched"]:
            comparative.append((metric, ", ".join(f"{row['title']}: {row['value']} {row['unit']} [{row['passage_id']}]"
                                                  for row in group["rows"])))
    if comparative:
        sections.append(("Comparable observations", comparative))
    buffer = BytesIO()
    if output_type == "markdown":
        lines = [f"# {escape(title)}"]
        for heading, entries in sections:
            lines.extend(("", f"## {heading}"))
            for text, source in entries:
                lines.extend(("", f"> {escape(text)}", "", escape(source)))
        return "\n".join(lines).encode()
    if output_type == "docx":
        doc = Document()
        doc.add_heading(title, 0)
        for heading, entries in sections:
            doc.add_heading(heading, level=1)
            for text, source in entries:
                doc.add_paragraph(text)
                if source:
                    doc.add_paragraph(source)
        doc.save(buffer)
    else:
        styles = getSampleStyleSheet()
        content = [Paragraph(escape(title), styles["Title"])]
        for heading, entries in sections:
            content.append(Paragraph(heading, styles["Heading1"]))
            for text, source in entries:
                content.append(Paragraph(escape(text), styles["BodyText"]))
                if source:
                    content.append(Paragraph(escape(source), styles["Italic"]))
                content.append(Spacer(1, 9))
        SimpleDocTemplate(buffer).build(content)
    return buffer.getvalue()


def references(result, style):
    sources = {}
    for claim in result.get("claims", []):
        for item in claim.get("supporting_evidence", [claim["evidence"]]):
            sources.setdefault(item["doi"] or item["document_id"], item)
    lines = []
    for index, item in enumerate(sources.values(), 1):
        meta = item["metadata"]
        authors = ", ".join(filter(None, meta.get("authors") or []))
        year = str(meta.get("year") or "n.d.")
        title = item["title"]
        journal = meta.get("journal")
        doi_link = "https://doi.org/" + item["doi"] if item.get("doi") else meta.get("url")
        if style == "ieee":
            identity = ". ".join(filter(None, [authors, f'"{title}"', journal, year, doi_link]))
            lines.append(f"[{index}] {identity}.")
        else:
            author_date = f"{authors}. ({year})." if authors else f"({year})."
            lines.append(" ".join(filter(None, [author_date, f"{title}.", f"{journal}." if journal else None, doi_link])))
    return "\n".join(lines) + ("\n" if lines else "")
