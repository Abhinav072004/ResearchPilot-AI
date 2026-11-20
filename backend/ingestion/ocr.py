import csv
import math
import re
import subprocess
from collections import defaultdict
from io import StringIO

import pymupdf

from app.config import settings

MAX_PIXELS = 10_000_000
MAX_DPI = 250
MIN_DPI = 100
LANGUAGES = re.compile(r"[a-zA-Z0-9_]+(?:\+[a-zA-Z0-9_]+)*")


def recognize(page, timeout):
    language = settings().ocr_languages
    if not LANGUAGES.fullmatch(language):
        raise ValueError("OCR language configuration is invalid")
    rect = page.rect
    if not rect.width or not rect.height:
        return []
    scale = min(MAX_DPI / 72, math.sqrt(MAX_PIXELS / (rect.width * rect.height)))
    if scale < MIN_DPI / 72:
        raise ValueError("Scanned page exceeds OCR rendering limits")
    pix = page.get_pixmap(matrix=pymupdf.Matrix(scale, scale), colorspace=pymupdf.csGRAY, alpha=False)
    if pix.width * pix.height > MAX_PIXELS:
        raise ValueError("Scanned page exceeds OCR rendering limits")
    try:
        command = ["tesseract", "stdin", "stdout", "-l", language, "--dpi", str(round(scale * 72)), "tsv"]
        result = subprocess.run(
            command, input=pix.tobytes("png"), capture_output=True, check=True, timeout=timeout,
        )
    except FileNotFoundError as exc:
        raise ValueError("Scanned PDF requires an installed Tesseract OCR engine") from exc
    except subprocess.TimeoutExpired as exc:
        raise ValueError("Scanned PDF exceeded the OCR time limit") from exc
    except subprocess.CalledProcessError as exc:
        raise ValueError("Tesseract could not read the scanned page") from exc

    paragraphs = defaultdict(list)
    for word in csv.DictReader(StringIO(result.stdout.decode()), delimiter="\t", quoting=csv.QUOTE_NONE):
        text = (word.get("text") or "").strip()
        if word["level"] == "5" and text:
            key = word["block_num"], word["par_num"]
            paragraphs[key].append((text, word))
    blocks = []
    for words in paragraphs.values():
        left = min(int(word["left"]) for _, word in words)
        top = min(int(word["top"]) for _, word in words)
        right = max(int(word["left"]) + int(word["width"]) for _, word in words)
        bottom = max(int(word["top"]) + int(word["height"]) for _, word in words)
        bounds = pymupdf.Rect(left / scale, top / scale, right / scale, bottom / scale)
        bounds *= page.derotation_matrix
        confidence = round(sum(float(word["conf"]) for _, word in words) / len(words), 1)
        blocks.append((" ".join(text for text, _ in words), list(bounds), confidence))
    return blocks
