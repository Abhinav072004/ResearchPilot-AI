"""Private Docling Serve integration for layout-aware PDF table extraction."""

import json
import logging
from time import monotonic

import httpx

from app.config import settings
from ingestion.tables import cell, table_payload

logger = logging.getLogger(__name__)


def extract_tables(content):
    endpoint = settings().docling_url
    if not endpoint:
        return []
    try:
        started = monotonic()
        payload = bytearray()
        with httpx.stream("POST", endpoint.rstrip("/") + "/v1/convert/file", follow_redirects=False,
                          timeout=httpx.Timeout(24, connect=3),
                          files={"files": ("document.pdf", content, "application/pdf")},
                          data={"to_formats": "json", "do_table_structure": "true", "do_ocr": "false"}) as response:
            response.raise_for_status()
            for chunk in response.iter_bytes(chunk_size=65536):
                if len(payload) + len(chunk) > 12_000_000 or monotonic() - started > 30:
                    raise ValueError("Docling response exceeds processing limits")
                payload.extend(chunk)
        result = json.loads(payload)
        if result["status"] not in {"success", "partial_success"}:
            raise ValueError("Docling conversion failed")
        document = result["document"]["json_content"]
        tables = []
        for node in document.get("tables", [])[:150]:
            provenance = node["prov"][0]
            page = int(provenance["page_no"])
            bbox = provenance["bbox"]
            bounds = [float(bbox[k]) for k in ("l", "t", "r", "b")]
            if bbox.get("coord_origin") == "BOTTOMLEFT":
                height = float(document["pages"][str(page)]["size"]["height"])
                bounds[1], bounds[3] = height - bounds[1], height - bounds[3]
            cells = [cell(int(c["start_row_offset_idx"]), int(c["start_col_offset_idx"]), c["text"],
                          header=bool(c.get("column_header") or c.get("row_header")),
                          rowspan=int(c.get("row_span", 1)), colspan=int(c.get("col_span", 1)))
                     for c in node["data"]["table_cells"][:5001]]
            if cells:
                tables.append((page, bounds, table_payload(cells)))
        return tables
    except (httpx.HTTPError, ValueError, KeyError, TypeError, IndexError, AttributeError):
        logger.warning("Docling table extraction unavailable; using native PDF parsing")
        return []
