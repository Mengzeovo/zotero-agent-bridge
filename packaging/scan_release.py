from __future__ import annotations

import argparse
import re
import zipfile
from pathlib import PurePosixPath


TEXT_SUFFIXES = {".css", ".ftl", ".html", ".js", ".json", ".md", ".py", ".rdf", ".toml", ".txt", ".xml"}
FORBIDDEN_NAMES = {
    "bridge.generated.json",
    "bridge-config.managed.json",
    "migration-state.json",
    "addon-status.json",
}
TOKEN_PATTERN = re.compile(r'"api_token"\s*:\s*"(?P<value>[^"<>]{16,})"', re.IGNORECASE)
WINDOWS_USER_PATH = re.compile(r"[A-Za-z]:[\\/]Users[\\/](?!<YOUR_USER>)[^\\/\s\"']+", re.IGNORECASE)


def scan(xpi_path, forbidden_fragments: list[str]) -> list[str]:
    findings: list[str] = []
    encoded_fragments = []
    for fragment in forbidden_fragments:
        if fragment:
            encoded_fragments.append((fragment, fragment.encode("utf-8"), fragment.encode("utf-16le")))
    with zipfile.ZipFile(xpi_path) as archive:
        for name in archive.namelist():
            path = PurePosixPath(name)
            if path.name in FORBIDDEN_NAMES:
                findings.append(f"forbidden file: {name}")
            data = archive.read(name)
            for label, utf8, utf16 in encoded_fragments:
                if utf8 in data or utf16 in data:
                    findings.append(f"machine path fragment {label!r}: {name}")
            if path.suffix.lower() not in TEXT_SUFFIXES:
                continue
            text = data.decode("utf-8", errors="replace")
            match = WINDOWS_USER_PATH.search(text)
            if match:
                findings.append(f"Windows user path {match.group(0)!r}: {name}")
            token = TOKEN_PATTERN.search(text)
            if token and token.group("value") not in {"YOUR_TOKEN", "CHANGE_ME"}:
                findings.append(f"embedded API token: {name}")
    return sorted(set(findings))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("xpi")
    parser.add_argument("--forbid", action="append", default=[])
    args = parser.parse_args()
    findings = scan(args.xpi, args.forbid)
    if findings:
        print("Release scan failed:")
        for finding in findings:
            print(f"- {finding}")
        raise SystemExit(1)
    print("Release scan passed")


if __name__ == "__main__":
    main()
