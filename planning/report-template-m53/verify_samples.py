"""Verify exported sample PDFs and render contact sheets with local PyMuPDF.

Run with the host Python (which has PyMuPDF), after convert_with_word.ps1.
Exact source paragraph ordering is checked in the DOCX builder. This independent
PDF check verifies character inventory, page bounds, draft labels and page numbers.
Word PDF extraction has Arabic ligature-order and spacing artifacts; do not claim
that extracted word order is identical. DOCX ordering and PDF visual review are
separate checks.
"""

from __future__ import annotations

import json
import hashlib
import re
import unicodedata
from collections import Counter
from pathlib import Path
from xml.etree import ElementTree
from zipfile import ZipFile

import pymupdf


ROOT = Path(__file__).resolve().parent / "output"
NS = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}


def words(text):
    text = unicodedata.normalize("NFKC", text)
    text = "".join(c for c in text if unicodedata.category(c) not in {"Cf", "Mn"})
    # PDF extractors can return Arabic glyphs in visual order. Canonicalize each
    # token's direction for the content-preservation check, not for stored source.
    tokens = []
    for token in re.findall(r"[^\W_]+", text, re.UNICODE):
        # Word's PDF ToUnicode map exposes some lam/alef ligatures in visual
        # order (e.g. ملاحظة -> مالحظة). Canonicalize only adjacent lam/alef
        # clusters in this extraction check; never alter the source or output.
        variants = []
        for variant in (token, token[::-1]):
            variants.append(re.sub(r"[لاأإآ]{2,}", lambda match: "".join(sorted(match[0])), variant))
        tokens.append(min(variants))
    return Counter(tokens)


def docx_body(path):
    with ZipFile(path) as archive:
        root = ElementTree.fromstring(archive.read("word/document.xml"))
    return "\n".join("".join(p.itertext()) for p in root.findall(".//w:t", NS))


def characters(text):
    return Counter(c for c in unicodedata.normalize("NFKC", text)
                   if not c.isspace() and unicodedata.category(c) != "Cf")


def main():
    results = []
    for pdf in sorted(ROOT.glob("*.pdf")):
        doc = pymupdf.open(pdf)
        expected = characters(docx_body(pdf.with_suffix(".docx")))
        # Exclude page header/footer and account for the repeated margin heading.
        observed = characters("\n".join(page.get_text(clip=pymupdf.Rect(0, 70, page.rect.width, 785))
                                         for page in doc))
        for char, count in characters("هامش").items():
            observed[char] -= count * (len(doc) - 1)
        missing, extra = expected - observed, observed - expected
        if missing or extra:
            raise AssertionError(f"{pdf.name}: character mismatch: missing={dict(missing)}, extra={dict(extra)}")
        for index, page in enumerate(doc):
            for x0, y0, x1, y1, *_ in page.get_text("words"):
                if not (12 <= x0 <= x1 <= page.rect.width - 12
                        and 12 <= y0 <= y1 <= page.rect.height - 12):
                    raise AssertionError(f"{pdf.name} page {index + 1}: text outside safe page bounds")
            page_tokens = words(page.get_text())
            if not words("غير معتمد") <= page_tokens and not words("غير معتمدة") <= page_tokens:
                raise AssertionError(f"{pdf.name} page {index + 1}: missing review notice")
            footer = page.get_text(clip=pymupdf.Rect(0, page.rect.height - 55, page.rect.width, page.rect.height))
            digits = [str(int(value)) for value in re.findall(r"\d+", footer)]
            if str(index + 1) not in digits or str(len(doc)) not in digits:
                raise AssertionError(f"{pdf.name} page {index + 1}: incorrect page counter {footer!r}")
        # A single long answer must really span pages, not be shrunk or cut off.
        if "long" in pdf.stem and len(doc) < 4:
            raise AssertionError("Long sample did not exercise sufficient page flow")
        preview = pymupdf.open()
        for start in range(0, len(doc), 4):
            sheet = preview.new_page(width=840, height=620)
            for offset, page in enumerate(list(doc)[start:start + 4]):
                x, y = (offset % 2) * 420, (offset // 2) * 310
                rect = pymupdf.Rect(x + 10, y + 10, x + 410, y + 300)
                sheet.show_pdf_page(rect, doc, start + offset)
            sheet.get_pixmap(matrix=pymupdf.Matrix(1.5, 1.5)).save(ROOT / f"{pdf.stem}-sheet-{start // 4 + 1}.png")
        # Refresh every page so no stale preview survives a layout revision.
        for index in range(len(doc)):
            doc[index].get_pixmap(matrix=pymupdf.Matrix(1.5, 1.5)).save(ROOT / f"{pdf.stem}-page-{index + 1}.png")
        results.append({"file": pdf.name, "pages": len(doc), "docx_body_character_inventory_matches": True,
                        "safe_page_bounds": True, "review_notice_each_page": True,
                        "page_counters": True, "native_word_visual_review": "pending"})
    if len(results) != 3:
        raise AssertionError(f"Expected three sample PDFs, found {len(results)}")
    (ROOT / "verification.json").write_text(json.dumps(results, indent=2) + "\n", encoding="utf-8")
    manifest_path = ROOT / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    conversion = ROOT / "word-conversion.json"
    if conversion.exists():
        manifest["converter"] = json.loads(conversion.read_text(encoding="utf-8-sig"))["converter"]
    manifest["artifacts"] = [item for item in manifest["artifacts"] if not item["file"].endswith(".pdf")]
    for result in results:
        pdf = ROOT / result["file"]
        manifest["artifacts"].append({"file": pdf.name, "sha256": hashlib.sha256(pdf.read_bytes()).hexdigest(),
                                      "bytes": pdf.stat().st_size, "pages": result["pages"]})
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
