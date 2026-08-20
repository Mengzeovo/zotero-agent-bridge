from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import uuid
import zipfile
from pathlib import Path, PurePosixPath


ZIP_TIMESTAMP = (2020, 1, 1, 0, 0, 0)
BUNDLE_XPI_ROOT = PurePosixPath("bridge/windows-x64")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def safe_relative(value: str) -> PurePosixPath:
    if not value or "\\" in value or "\x00" in value:
        raise ValueError(f"Unsafe archive path: {value!r}")
    path = PurePosixPath(value)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise ValueError(f"Unsafe archive path: {value!r}")
    if len(path.parts[0]) >= 2 and path.parts[0][1:2] == ":":
        raise ValueError(f"Unsafe archive path: {value!r}")
    return path


def load_and_verify_bundle(bundle_root: Path) -> tuple[dict, list[tuple[Path, PurePosixPath]]]:
    bundle_root = bundle_root.resolve()
    manifest_path = bundle_root / "bridge-manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("bundle_schema_version") != 1:
        raise ValueError("Unsupported bundle schema")
    if manifest.get("platform") != "windows" or manifest.get("architecture") != "x64":
        raise ValueError("Bundle platform/architecture mismatch")
    records = manifest.get("files")
    if not isinstance(records, list) or not records:
        raise ValueError("Bundle manifest has no files")

    expected: dict[str, dict] = {}
    verified: list[tuple[Path, PurePosixPath]] = []
    for record in records:
        if not isinstance(record, dict):
            raise ValueError("Invalid bundle file record")
        archive_path = safe_relative(str(record.get("path") or ""))
        key = archive_path.as_posix()
        if key in expected:
            raise ValueError(f"Duplicate bundle path: {key}")
        source = bundle_root.joinpath(*archive_path.parts).resolve()
        if bundle_root not in source.parents:
            raise ValueError(f"Bundle file escapes root: {key}")
        if not source.is_file() or source.is_symlink():
            raise ValueError(f"Bundle file is missing or unsupported: {key}")
        size = source.stat().st_size
        digest = sha256_file(source)
        if size != record.get("size") or digest != record.get("sha256"):
            raise ValueError(f"Bundle file verification failed: {key}")
        expected[key] = record
        verified.append((source, BUNDLE_XPI_ROOT / archive_path))

    bundle_dir = bundle_root / "zab-bridge"
    actual = {
        f"zab-bridge/{path.relative_to(bundle_dir).as_posix()}"
        for path in bundle_dir.rglob("*")
        if path.is_file()
    }
    if actual != set(expected):
        missing = sorted(set(expected) - actual)
        extra = sorted(actual - set(expected))
        raise ValueError(f"Bundle file set mismatch; missing={missing}, extra={extra}")
    if manifest.get("entrypoint") not in expected:
        raise ValueError("Bundle entrypoint is not listed in files")
    return manifest, verified


def addon_files(addon_root: Path) -> list[tuple[Path, PurePosixPath]]:
    addon_root = addon_root.resolve()
    files: list[tuple[Path, PurePosixPath]] = []
    for path in sorted(addon_root.rglob("*"), key=lambda item: item.as_posix()):
        if not path.is_file():
            continue
        relative = safe_relative(path.relative_to(addon_root).as_posix())
        if relative.parts[0] == "bridge":
            raise ValueError("Addon source must not contain an unmanaged bridge directory")
        files.append((path, relative))
    return files


def write_entry(archive: zipfile.ZipFile, source: Path, target: PurePosixPath) -> None:
    info = zipfile.ZipInfo(target.as_posix(), ZIP_TIMESTAMP)
    info.compress_type = zipfile.ZIP_DEFLATED
    info.external_attr = 0o100644 << 16
    with source.open("rb") as handle:
        archive.writestr(info, handle.read(), compress_type=zipfile.ZIP_DEFLATED, compresslevel=9)


def build_xpi(addon_root: Path, bundle_root: Path, output: Path) -> dict:
    manifest, bundle_files = load_and_verify_bundle(bundle_root)
    entries = addon_files(addon_root)
    entries.append((bundle_root / "bridge-manifest.json", BUNDLE_XPI_ROOT / "bridge-manifest.json"))
    for metadata_name in ("SBOM.cdx.json", "THIRD_PARTY_NOTICES.md"):
        metadata_path = bundle_root / metadata_name
        if metadata_path.is_file():
            entries.append((metadata_path, BUNDLE_XPI_ROOT / metadata_name))
    entries.extend(bundle_files)
    targets = [target.as_posix() for _, target in entries]
    if len(targets) != len(set(targets)):
        raise ValueError("Duplicate XPI archive path")

    output = output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(f".{output.name}.tmp-{uuid.uuid4().hex}")
    try:
        with zipfile.ZipFile(temporary, "w", allowZip64=True) as archive:
            for source, target in sorted(entries, key=lambda entry: entry[1].as_posix()):
                write_entry(archive, source, target)
        os.replace(temporary, output)
    finally:
        if temporary.exists():
            temporary.unlink()
    return {
        "output": str(output),
        "bridge_version": manifest["bridge_version"],
        "files": len(entries),
        "size": output.stat().st_size,
        "sha512": hashlib.sha512(output.read_bytes()).hexdigest(),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--addon-root", required=True, type=Path)
    parser.add_argument("--bundle-root", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--compat-output", type=Path)
    args = parser.parse_args()
    result = build_xpi(args.addon_root, args.bundle_root, args.output)
    if args.compat_output:
        args.compat_output.parent.mkdir(parents=True, exist_ok=True)
        temporary = args.compat_output.with_name(f".{args.compat_output.name}.tmp-{uuid.uuid4().hex}")
        shutil.copyfile(args.output, temporary)
        os.replace(temporary, args.compat_output)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
