from __future__ import annotations

import argparse
import hashlib
import json
import platform
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath


BUNDLE_SCHEMA_VERSION = 1
PROTOCOL_VERSION = 2
PRODUCT_SCOPE = "zotero-pi-only"
DISTRIBUTION = "xpi-bundled"
PLATFORM = "windows"
ARCHITECTURE = "x64"
SENTINEL = ".zab-bundle-installed.json"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def source_revision(project_root: Path) -> str:
    try:
        commit = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=project_root, text=True, stderr=subprocess.DEVNULL
        ).strip()
        dirty = subprocess.run(
            ["git", "diff", "--quiet"], cwd=project_root, check=False
        ).returncode != 0
        untracked = subprocess.check_output(
            ["git", "ls-files", "--others", "--exclude-standard"],
            cwd=project_root,
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
        return f"git:{commit}{'-dirty' if dirty or untracked else ''}"
    except (OSError, subprocess.SubprocessError):
        return "source:unknown"


def validate_relative_path(value: str) -> None:
    if not value or "\\" in value or "\x00" in value:
        raise ValueError(f"Unsafe bundle path: {value!r}")
    path = PurePosixPath(value)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise ValueError(f"Unsafe bundle path: {value!r}")
    if len(path.parts[0]) >= 2 and path.parts[0][1:2] == ":":
        raise ValueError(f"Unsafe bundle path: {value!r}")


def build_manifest(bundle_dir: Path, bridge_version: str, project_root: Path) -> dict[str, object]:
    bundle_dir = bundle_dir.resolve()
    if not bundle_dir.is_dir():
        raise ValueError(f"Bundle directory does not exist: {bundle_dir}")
    entrypoint = f"{bundle_dir.name}/zab-bridge.exe"
    files: list[dict[str, object]] = []
    seen: set[str] = set()
    for path in sorted((item for item in bundle_dir.rglob("*") if item.is_file()), key=lambda item: item.as_posix()):
        relative = f"{bundle_dir.name}/{path.relative_to(bundle_dir).as_posix()}"
        validate_relative_path(relative)
        if relative in seen:
            raise ValueError(f"Duplicate bundle path: {relative}")
        seen.add(relative)
        files.append({"path": relative, "size": path.stat().st_size, "sha256": sha256_file(path)})
    if entrypoint not in seen:
        raise ValueError(f"Frozen Bridge entrypoint is missing: {entrypoint}")
    return {
        "bundle_schema_version": BUNDLE_SCHEMA_VERSION,
        "bridge_version": bridge_version,
        "protocol_version": PROTOCOL_VERSION,
        "product_scope": PRODUCT_SCOPE,
        "distribution": DISTRIBUTION,
        "platform": PLATFORM,
        "architecture": ARCHITECTURE,
        "entrypoint": entrypoint,
        "sentinel": SENTINEL,
        "build": {
            "python_version": platform.python_version(),
            "pyinstaller_version": _pyinstaller_version(),
            "built_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
            "source_revision": source_revision(project_root),
        },
        "files": files,
    }


def _pyinstaller_version() -> str:
    try:
        import PyInstaller

        return str(PyInstaller.__version__)
    except ImportError:
        return "unknown"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--bundle-dir", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--bridge-version", required=True)
    parser.add_argument("--project-root", required=True, type=Path)
    args = parser.parse_args()
    manifest = build_manifest(args.bundle_dir, args.bridge_version, args.project_root.resolve())
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(args.output)
    print(f"files={len(manifest['files'])}")


if __name__ == "__main__":
    main()
