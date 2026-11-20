"""Bounded, source-located table representations shared by the parsers."""


def cell(row, column, text, *, header=False, rowspan=1, colspan=1):
    return {"row": row, "column": column, "rowspan": rowspan, "colspan": colspan, "header": header,
            "text": " ".join((text or "").split())[:2000]}


def table_payload(cells, caption=""):
    if len(cells) > 5000:
        raise ValueError("Document table exceeds the supported cell count")
    return {"caption": caption[:4000], "cells": cells}


def table_text(table):
    rows = {}
    for value in table["cells"]:
        rows.setdefault(value["row"], []).append(value)
    entries = [" | ".join(cell["text"] for cell in sorted(cells, key=lambda item: item["column"]))
               for _, cells in sorted(rows.items())]
    return "\n".join(part for part in [table["caption"], *entries] if part.strip())


def jats_table(element, text):
    table = element if element.tag == "table" else element.find(".//table")
    caption = element.find("caption")
    caption_text = text(caption) if caption is not None else ""
    cells, occupied = [], set()
    if table is None:
        return None
    for row_index, row in enumerate(table.findall(".//tr")):
        column = 0
        for item in row:
            if item.tag not in {"th", "td"}:
                continue
            while (row_index, column) in occupied:
                column += 1
            try:
                rowspan, colspan = [min(50, max(1, int(item.get(key, "1")))) for key in ("rowspan", "colspan")]
            except ValueError:
                rowspan, colspan = 1, 1
            if len(cells) >= 5000 or len(occupied) + rowspan * colspan > 20_000 or column + colspan > 120:
                raise ValueError("Document table exceeds the supported grid size")
            cells.append(cell(row_index, column, text(item), header=item.tag == "th", rowspan=rowspan, colspan=colspan))
            if row_index >= 500:
                raise ValueError("Document table exceeds the supported cell count")
            for r in range(row_index, row_index + rowspan):
                for c in range(column, column + colspan):
                    occupied.add((r, c))
            column += colspan
    return table_payload(cells, caption_text) if cells else None
