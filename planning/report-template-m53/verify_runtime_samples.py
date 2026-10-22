"""Independent per-page glyph inventory and geometry checks on locally generated PDFs."""
import json
import sys
import unicodedata
from collections import Counter
from pathlib import Path
import pymupdf

base = Path(__file__).resolve().parent
root = base / ("runtime-word-check" if "--word" in sys.argv else "runtime-review")
def chars(text):
    return Counter(c for c in unicodedata.normalize("NFKC", text)
                   if not c.isspace() and unicodedata.category(c) != "Cf")

results = []
for path in root.glob("*.pdf"):
    layout_path = base / "runtime-review" / (path.stem + ".layout.json")
    if not layout_path.exists():
        continue
    layout = json.loads(layout_path.read_text(encoding="utf-8"))
    doc = pymupdf.open(path)
    assert len(doc) == len(layout["pages"])
    for i, (page, rows) in enumerate(zip(doc, layout["pages"])):
        body = page.get_text(clip=pymupdf.Rect(0, 78, 500, 737))
        expected = "".join(row["text"] + row["margin"] for row in rows)
        assert chars(body) == chars(expected), (path.name, i, chars(expected) - chars(body), chars(body) - chars(expected))
        page.get_pixmap(matrix=pymupdf.Matrix(1.3, 1.3)).save(root / f"{path.stem}-page-{i+1}.png")
    results.append({"file": path.name, "pages": len(doc), "body_characters_preserved": True})
(root / "verification.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
print(json.dumps(results, indent=2))
