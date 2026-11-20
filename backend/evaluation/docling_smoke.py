"""Verify real Docling Serve table extraction against a generated PDF grid."""

from io import BytesIO

from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Table

from app.config import settings
from ingestion.parser import pdf_blocks


def sample():
    target = BytesIO()
    table = Table([["Metric", "Value", "Unit"],
                   ["Hydrogen yield", "12.50", "mol/kg"],
                   ["Cold gas efficiency", "67.2", "%"]], colWidths=[190, 80, 80])
    table.setStyle([("GRID", (0, 0), (-1, -1), 1, colors.black)])
    SimpleDocTemplate(target).build([table])
    return target.getvalue()


def main():
    if not settings().docling_url:
        raise ValueError("Set RP_DOCLING_URL to the private Docling Serve endpoint")
    tables = [block for block in pdf_blocks(sample()) if block.anchor.get("extractor") == "docling"]
    cells = {cell["text"] for block in tables for cell in block.structure["cells"]}
    assert {"Hydrogen yield", "12.50", "mol/kg"} <= cells, cells
    assert tables[0].page == 1 and tables[0].anchor["bbox"]
    print("Docling returned the expected cells and page coordinates.")


if __name__ == "__main__":
    main()
