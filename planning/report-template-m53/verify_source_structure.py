"""Independent per-page PDF checks for the ruled, source-structure specimens."""
import hashlib
import json
from pathlib import Path

import pymupdf

from verify_samples import characters

ROOT = Path(__file__).resolve().parent / "source-structure"
results = []
artifacts = []
for path in sorted(ROOT.glob("m53-source-*.pdf")):
    planned = json.loads(path.with_suffix(".layout.json").read_text(encoding="utf-8"))
    doc = pymupdf.open(path)
    assert len(doc) == len(planned), f"{path.name}: unexpected pagination"
    for index, page in enumerate(doc):
        expected = characters(" ".join(row["text"] + " " + row["margin"] for row in planned[index]))
        actual = characters(page.get_text(clip=pymupdf.Rect(0, 78, 595, 734)))
        assert expected == actual, (path.name, index + 1, dict(expected - actual), dict(actual - expected))
        # The header/footer are outside the source form's fixed 28-line grid.
        header = page.get_text(clip=pymupdf.Rect(0, 0, 595, 78))
        assert characters("غير معتمد") <= characters(header), f"{path.name}: missing review notice"
        assert str(index + 1) in header, f"{path.name}: incorrect report page number"
        for x0, y0, x1, y1, *_ in page.get_text("words"):
            assert 4 <= x0 <= x1 <= 590 and 4 <= y0 <= y1 <= 838, f"{path.name}: out-of-page text"
        page.get_pixmap(matrix=pymupdf.Matrix(1.35, 1.35)).save(ROOT / f"{path.stem}-page-{index + 1}.png")
    results.append({"file": path.name, "pages": len(doc), "planned_page_count_matches": True,
                    "per_page_character_inventory_matches": True, "review_notices": True,
                    "page_numbers": True, "page_bounds": True})
assert len(results) == 3
for path in sorted(ROOT.iterdir()):
    if path.suffix in {".docx", ".pdf"}:
        artifacts.append({"file": path.name, "bytes": path.stat().st_size,
                          "sha256": hashlib.sha256(path.read_bytes()).hexdigest()})
manifest = {"classification": "reconstructed_for_review", "variables": 56,
            "converter": "Microsoft Word 16.0, local desktop SaveAs2 PDF",
            "checks": results, "artifacts": artifacts,
            "limitations": ["Not a deployed application template", "Scan-based reconstruction, not verified pixel-identical",
                            "Arabic PDF extraction order differs from logical source order; character inventories are compared",
                            "Institutional acceptance and interactive Word editing/printing review remain pending"]}
(ROOT / "verification.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print(json.dumps(results, indent=2))
