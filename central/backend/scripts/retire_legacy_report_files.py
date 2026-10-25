"""Inventory before migration, then remove only unchanged, explicitly inventoried legacy files.

Usage: python scripts/retire_legacy_report_files.py /storage/backups/.../legacy-files.json
       python scripts/retire_legacy_report_files.py /storage/backups/.../legacy-files.json --purge
"""
import argparse
import hashlib
import json
from pathlib import Path
from sqlalchemy import text
from app.config import get_settings
from app.db.session import engine


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--purge", action="store_true")
    args = parser.parse_args()
    root = get_settings().storage_root.resolve()

    def confined(relative):
        path = (root / relative).resolve()
        if root not in path.parents or Path(relative).parts[0] not in {"reports", "report-templates"}:
            raise ValueError("Refusing a path outside legacy report storage")
        return path

    if not args.purge:
        with engine.connect() as connection:
            paths = connection.execute(text("SELECT storage_path FROM report_template_versions")).scalars().all()
            for row in connection.execute(text("SELECT storage_path,pdf_path,context_path FROM generated_reports WHERE format_key IS DISTINCT FROM 'statement-html-1'")):
                paths.extend(value for value in row if value)
        templates = root / "report-templates"
        if templates.exists():
            paths.extend(str(p.relative_to(root)) for p in templates.rglob("*") if p.is_file())
        files = []
        for relative in sorted(set(paths)):
            path = confined(relative)
            if path.is_file():
                files.append({"path": relative, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()})
        args.manifest.parent.mkdir(parents=True, exist_ok=True)
        args.manifest.write_text(json.dumps({"files": files}, indent=2), encoding="utf-8")
        print(f"Inventoried {len(files)} legacy files")
        return

    with engine.connect() as connection:
        if connection.scalar(text("SELECT count(*) FROM generated_reports WHERE format_key IS DISTINCT FROM 'statement-html-1'")):
            raise RuntimeError("Apply the retirement migration before removing files")
        active = set(connection.execute(text("SELECT html_path FROM generated_reports UNION SELECT pdf_path FROM generated_reports UNION SELECT context_path FROM generated_reports")).scalars())
    files = json.loads(args.manifest.read_text(encoding="utf-8"))["files"]
    # Validate the entire manifest before any deletion; a changed file aborts the operation.
    targets = []
    for item in files:
        path = confined(item["path"])
        if item["path"] in active:
            raise RuntimeError("A current HTML report references a legacy candidate")
        if path.exists():
            if hashlib.sha256(path.read_bytes()).hexdigest() != item["sha256"]:
                raise RuntimeError("Legacy file changed since inventory")
            targets.append(path)
    for path in targets:
        path.unlink()
    print(f"Removed {len(targets)} inventoried legacy files; investigation evidence untouched")


if __name__ == "__main__":
    main()
