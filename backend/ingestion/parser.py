import re
from dataclasses import replace
from dataclasses import dataclass, field

import httpx
import pymupdf
from defusedxml import ElementTree

from app.config import settings


@dataclass(frozen=True)
class Block:
    heading: str
    text: str
    page: int | None = None
    kind: str = "paragraph"
    anchor: dict = field(default_factory=dict)


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
    with pymupdf.open(stream=content, filetype="pdf") as doc:
        if doc.is_encrypted or not 0 < len(doc) <= 250:
            raise ValueError("Encrypted, empty or oversized PDF")
        for page in doc:
            for x0, y0, x1, y1, raw, _, type_id in page.get_text("blocks", sort=True):
                if type_id != 0:
                    continue
                text = re.sub(r"\s+", " ", raw).strip()
                if HEADINGS.fullmatch(text):
                    heading = text
                elif text:
                    blocks.append(Block(heading, text, page.number + 1, kind_for(text),
                                        {"bbox": [x0, y0, x1, y1], "extractor": "pymupdf"}))
    return blocks


def xml_blocks(content):
    root = ElementTree.fromstring(content)
    for element in root.iter():
        element.tag = element.tag.rsplit("}", 1)[-1]

    def copied_text(element):
        return re.sub(r"\s+", " ", " ".join(element.itertext())).strip()

    def walk(element, heading="Document", path="1"):
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
            text = copied_text(node)
            if text:
                yield Block(heading, text, None, kind, {"xml_path": path, "extractor": "xml"})
            return
        for index, child in enumerate(element, 1):
            yield from walk(child, heading, f"{path}/{index}")

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
            result.append(replace(block, text=block.text[offset:end],
                                  anchor={**block.anchor, "character_start": offset, "character_end": end}))
            offset = end + int(block.text[end] == " ")
        if offset:
            result.append(replace(block, text=block.text[offset:],
                                  anchor={**block.anchor, "character_start": offset,
                                          "character_end": len(block.text)}))
        else:
            result.append(block)
    return result
