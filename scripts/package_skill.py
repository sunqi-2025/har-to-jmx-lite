#!/usr/bin/env python3
"""Build and verify a clean marketplace-ready ZIP archive for har-to-jmx-lite."""

from __future__ import annotations

import argparse
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

SKILL_NAME = "har-to-jmx-lite"


def build_package(repo_root: Path, output_zip: Path) -> Path:
    repo_root = repo_root.resolve()
    output_zip = output_zip.resolve()
    output_zip.parent.mkdir(parents=True, exist_ok=True)

    included_files = [
        ("SKILL.md", repo_root / "SKILL.md"),
        ("LICENSE", repo_root / "LICENSE"),
        ("scripts/__init__.py", repo_root / "scripts" / "__init__.py"),
        ("scripts/har_to_jmx_lite.py", repo_root / "scripts" / "har_to_jmx_lite.py"),
        ("references/jmeter-guardrails.md", repo_root / "references" / "jmeter-guardrails.md"),
        ("examples/sample_shop_api.har", repo_root / "examples" / "sample_shop_api.har"),
        ("tests/test_har_to_jmx_lite.py", repo_root / "tests" / "test_har_to_jmx_lite.py"),
    ]

    for rel, src in included_files:
        if not src.is_file():
            raise FileNotFoundError(f"Missing required asset: {src} ({rel})")

    with zipfile.ZipFile(output_zip, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for rel, src in included_files:
            zf.write(src, arcname=f"{SKILL_NAME}/{rel}")

    return output_zip


def verify_package(zip_path: Path) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        with zipfile.ZipFile(zip_path, "r") as zf:
            top_levels = {n.split("/", 1)[0] for n in zf.namelist()}
            if top_levels != {SKILL_NAME}:
                raise RuntimeError(f"ZIP must unpack into '{SKILL_NAME}/', got {sorted(top_levels)}")
            zf.extractall(tmp_path)

        extracted = tmp_path / SKILL_NAME
        res = subprocess.run(
            [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-v"],
            cwd=str(extracted),
            capture_output=True,
            text=True,
            check=False,
        )
        if res.returncode != 0:
            raise RuntimeError(f"Packaged tests failed:\n{res.stdout}\n{res.stderr}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build and verify clean ZIP for har-to-jmx-lite.")
    parser.add_argument("--output", default=f"dist/{SKILL_NAME}.zip")
    args = parser.parse_args(argv)

    repo_root = Path(__file__).resolve().parents[1]
    out_path = Path(args.output) if Path(args.output).is_absolute() else repo_root / args.output
    zip_path = build_package(repo_root, out_path)
    verify_package(zip_path)
    print(f"OK: built and verified {zip_path} ({zip_path.stat().st_size / 1024.0:.1f} KB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
