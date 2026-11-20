import re
from dataclasses import dataclass, field, replace
from time import monotonic

import httpx
import pymupdf
from defusedxml import ElementTree

from app.config import settings
from ingestion.docling_client import extract_tables
from ingestion.ocr import recognize
from ingestion.tables import cell, jats_table, table_payload, table_text


@dataclass(frozen=True)
class Block:
    heading: str
    text: str
    page: int | None = None
    kind: str = "paragraph"
    anchor: dict = field(default_factory=dict)
    structure: dict | None = None


HEADINGS = re.compile(r"^(?:\d+(?:\.\d+)*\.?\s+)?(?:abstract|introduction|background|materials and methods|"
                      r"methods|methodology|experimental setup|results(?: and discussion)?|discussion|limitations|"
                      r"conclusions?|references|future work|appendix)$", re.I)


def kind_for(text):
    if re.match(r"^table\s+\w+\s*[:.]", text, re.I):
        return "table"
    if re.match(r"^(?:figure|fig\.)\s+\w+", text, re.I):
        return "figure_caption"
    if re.match(r"^(?:equation|eq\.)\s+\w+", text, re.I):
        return "equation"
    return "paragraph"


def pdf_blocks(content):
    heading = "Document"
    blocks = []
    scans = 0
    with pymupdf.open(stream=content, filetype="pdf") as doc:
        if doc.is_encrypted or not 0 < len(doc) <= 250:
            raise ValueError("Encrypted, empty or oversized PDF")
        budget = monotonic() + 85
        tables_by_page = {}
        for page_number, bounds, table in extract_tables(content):
            if 1 <= page_number <= len(doc):
                tables_by_page.setdefault(page_number, []).append((bounds, table, "docling"))
        for page in doc:
            native = [(text.strip(), [x0, y0, x1, y1], None)
                      for x0, y0, x1, y1, text, _, kind in page.get_text("blocks", sort=True)
                      if kind == 0 and text.strip()]
            page_blocks = native
            if not native and page.get_image_info():
                scans += 1
                remaining = budget - monotonic()
                if scans > 35 or remaining <= 0:
                    raise ValueError("Scanned PDF exceeds OCR processing limits. Split it into smaller files.")
                page_blocks = recognize(page, timeout=min(18, remaining))
            for raw, bounds, confidence in page_blocks:
                text = re.sub(r"\s+", " ", raw).strip()
                if HEADINGS.fullmatch(text):
                    heading = text
                elif text:
                    anchor = {"bbox": bounds, "extractor": "pymupdf" if confidence is None else "tesseract"}
                    if confidence is not None:
                        anchor["ocr_confidence"] = confidence
                    blocks.append(Block(heading, text, page.number + 1, kind_for(text), anchor))
            detected = tables_by_page.get(page.number + 1, [])
            if not detected and native and len(native) >= 3:
                # Native grid extraction remains available when Docling is disabled.
                for table in page.find_tables().tables[:30]:
                    cells = []
                    for row, values in enumerate(table.extract()[:300]):
                        for column, text in enumerate(values[:40]):
                            cells.append(cell(row, column, text, header=row == 0 and not table.header.external))
                    if not cells:
                        continue
                    if table.header.external:
                        cells = [cell(-1, column, name, header=True) for column, name in enumerate(table.header.names)] + cells
                    detected.append((list(table.bbox), table_payload(cells), "pymupdf-table"))
            for bounds, table, extractor in detected:
                blocks.append(Block(heading, table_text(table), page.number + 1, "table",
                                    {"bbox": bounds, "extractor": extractor}, table))
    return blocks


def xml_blocks(content):
    root = ElementTree.fromstring(content)
    for element in root.iter():
        element.tag = element.tag.rsplit("}", 1)[-1]

    def copied_text(element):
        return re.sub(r"\s+", " ", " ".join(element.itertext())).strip()

    def walk(element, heading="Document", path="1", depth=0):
        if depth > 100:
            raise ValueError("Document XML exceeds the supported nesting level")
        tags = {"p": "paragraph", "table-wrap": "table", "table": "table", "fig": "figure_caption",
                "figure": "figure_caption", "disp-formula": "equation", "formula": "equation", "ref": "reference"}
        if element.tag in ("sec", "div", "abstract", "ref-list"):
            name = element.find("title")
            if name is None:
                name = element.find("head")
            heading = copied_text(name) if name is not None else {
                "abstract": "Abstract", "ref-list": "References"
            }.get(element.tag, heading)
        if element.tag in tags:
            node = element
            figure_type = element.get("type") == "table"
            kind = "table" if figure_type else tags[element.tag]
            if kind == "figure_caption":
                node = element.find("caption")
                if node is None:
                    node = element.find("figDesc")
                if node is None:
                    return
            structure = None
            if kind == "table":
                structure = jats_table(element, copied_text)
            elif kind in {"figure_caption", "equation", "reference"}:
                label = element.findtext("label")
                structure = {"label": label.strip() if label else "", "text": copied_text(node)}
                doi = element.find(".//pub-id[@pub-id-type='doi']")
                if doi is not None and doi.text:
                    structure["doi"] = doi.text.strip()
            text = table_text(structure) if kind == "table" and structure else copied_text(node)
            if text:
                yield Block(heading, text, None, kind, {"xml_path": path, "extractor": "xml"}, structure)
            return
        for index, child in enumerate(element, 1):
            yield from walk(child, heading, f"{path}/{index}", depth + 1)

    return list(walk(root))


def parse(content, content_type):
    if content_type == "application/pdf":
        blocks = pdf_blocks(content)
        if settings().grobid_url:
            try:
                response = httpx.post(settings().grobid_url.rstrip("/") + "/api/processFulltextDocument",
                                      files={"input": ("document.pdf", content, content_type)}, timeout=25)
                parsed = xml_blocks(response.raise_for_status().content)
                # Retain page-located primary evidence and structured XML blocks.
                blocks.extend(b for b in parsed if b.kind != "paragraph")
            except (httpx.HTTPError, ValueError, ElementTree.ParseError):
                if not blocks:
                    raise ValueError("PDF structure extraction failed") from None
    else:
        blocks = xml_blocks(content)
    if not blocks:
        raise ValueError("No machine-readable text was extracted")
    if len(blocks) > 12000 or sum(len(b.text) for b in blocks) > 4_000_000:
        raise ValueError("Document exceeds extraction limits")
    result = []
    for block in blocks:
        offset = 0
        while len(block.text) - offset > 6000:
            end = block.text.rfind(" ", offset + 3000, offset + 6000)
            end = offset + 6000 if end < 0 else end
            result.append(replace(block, text=block.text[offset:end], structure=block.structure if offset == 0 else None,
                                  anchor={**block.anchor, "character_start": offset, "character_end": end}))
            offset = end + int(block.text[end] == " ")
        if offset:
            result.append(replace(block, text=block.text[offset:], structure=None,
                                  anchor={**block.anchor, "character_start": offset,
                                          "character_end": len(block.text)}))
        else:
            result.append(block)
    return result
