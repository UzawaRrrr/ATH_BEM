#!/usr/bin/env python
from __future__ import annotations

import argparse
import shutil
import sys
import urllib.request
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_URL = "https://at-horns.eu/release/ath-2025-06.zip"
DEFAULT_TOOLS_DIR = ROOT / "tools" / "ath"
TRITONIA_BASE_URL = "https://at-horns.eu/"
TRITONIA_FILES = {
    "Tritonia": "ext/Tritonia.txt",
    "Tritonia-S": "ext/Tritonia-S.txt",
    "Tritonia-M": "ext/Tritonia-M.txt",
}
DEFAULT_TRITONIA_DB_DIR = ROOT / "config" / "ath_database" / "tritonia"


def _download(url: str, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    with urllib.request.urlopen(url) as response, dest.open("wb") as fp:
        shutil.copyfileobj(response, fp)


def _find_ath_executable(extracted_root: Path) -> Path | None:
    for candidate in extracted_root.rglob("ath.exe"):
        if candidate.is_file():
            return candidate
    return None


def _download_text(url: str, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    with urllib.request.urlopen(url) as response:
        content = response.read()
    dest.write_bytes(content)


def _install_tritonia_database(target_dir: Path) -> None:
    target_dir.mkdir(parents=True, exist_ok=True)

    for model, relative in TRITONIA_FILES.items():
        source_url = TRITONIA_BASE_URL + relative
        txt_path = target_dir / f"{model}.txt"
        cfg_path = target_dir / f"{model}.cfg"
        _download_text(source_url, txt_path)
        shutil.copyfile(txt_path, cfg_path)

    # On the official Tritonia page, XS and F currently point to Tritonia-M Ath code.
    for alias in ("Tritonia-XS", "Tritonia-F"):
        shutil.copyfile(target_dir / "Tritonia-M.cfg", target_dir / f"{alias}.cfg")

    index_content = """# Tritonia ATH config index (synced from at-horns.eu)
models:
  - name: Tritonia
    local_cfg: Tritonia.cfg
    source: https://at-horns.eu/ext/Tritonia.txt
    note: original Tritonia Ath code
  - name: Tritonia-S
    local_cfg: Tritonia-S.cfg
    source: https://at-horns.eu/ext/Tritonia-S.txt
    note: official Tritonia-S Ath code
  - name: Tritonia-M
    local_cfg: Tritonia-M.cfg
    source: https://at-horns.eu/ext/Tritonia-M.txt
    note: official Tritonia-M Ath code
  - name: Tritonia-XS
    local_cfg: Tritonia-XS.cfg
    source: https://at-horns.eu/ext/Tritonia-M.txt
    note: Tritonia page links XS Ath code to Tritonia-M source
  - name: Tritonia-F
    local_cfg: Tritonia-F.cfg
    source: https://at-horns.eu/ext/Tritonia-M.txt
    note: Tritonia page links F Ath code to Tritonia-M source
"""
    (target_dir / "index.yaml").write_text(index_content, encoding="utf-8")


def _update_local_config(ath_executable: Path, config_path: Path) -> None:
    if not config_path.exists():
        return

    lines = config_path.read_text(encoding="utf-8").splitlines()
    relative = ath_executable.relative_to(ROOT).as_posix()
    updated = []
    changed = False
    for line in lines:
        if line.strip().startswith("ath_executable:"):
            prefix = line.split("ath_executable:")[0]
            updated.append(f'{prefix}ath_executable: "{relative}"')
            changed = True
        else:
            updated.append(line)
    if changed:
        config_path.write_text("\n".join(updated) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Install ATH from official at-horns release zip.")
    parser.add_argument("--url", default=DEFAULT_URL, help="ATH zip URL")
    parser.add_argument("--tools-dir", type=Path, default=DEFAULT_TOOLS_DIR)
    parser.add_argument("--tritonia-db-dir", type=Path, default=DEFAULT_TRITONIA_DB_DIR)
    parser.add_argument("--force", action="store_true", help="Re-download even if target exists")
    parser.add_argument(
        "--update-config",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Update config/local_paths.yaml",
    )
    parser.add_argument(
        "--with-tritonia",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Download Tritonia ATH configs into local database",
    )
    args = parser.parse_args()

    tools_dir = args.tools_dir.resolve()
    zip_name = Path(args.url).name
    zip_path = tools_dir / zip_name
    extracted_dir = tools_dir / zip_name.removesuffix(".zip")

    if args.force and zip_path.exists():
        zip_path.unlink()
    if args.force and extracted_dir.exists():
        shutil.rmtree(extracted_dir)

    if not zip_path.exists():
        print(f"[INFO] Downloading {args.url}")
        _download(args.url, zip_path)
    else:
        print(f"[INFO] Reusing existing zip: {zip_path}")

    if not extracted_dir.exists():
        print(f"[INFO] Extracting to {extracted_dir}")
        with zipfile.ZipFile(zip_path, "r") as zf:
            zf.extractall(extracted_dir)
    else:
        print(f"[INFO] Reusing existing extracted directory: {extracted_dir}")

    ath_exe = _find_ath_executable(extracted_dir)
    if not ath_exe:
        print("[FAIL] ath.exe was not found in extracted archive.")
        return 1

    ath_cfg = ath_exe.parent / "ath.cfg"
    if not ath_cfg.exists():
        print(f"[FAIL] ath.cfg not found near executable: {ath_cfg}")
        return 1

    print(f"[PASS] ath executable: {ath_exe}")
    print(f"[PASS] ath cfg: {ath_cfg}")

    if args.update_config:
        config_path = ROOT / "config" / "local_paths.yaml"
        _update_local_config(ath_exe, config_path)
        print(f"[INFO] Updated config: {config_path}")

    if args.with_tritonia:
        _install_tritonia_database(args.tritonia_db_dir.resolve())
        print(f"[INFO] Tritonia database synced: {args.tritonia_db_dir.resolve()}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
