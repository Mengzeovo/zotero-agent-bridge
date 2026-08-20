from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import re
from datetime import UTC, datetime
from pathlib import Path


RUNTIME_PACKAGES = {
    "zotero-agent-bridge",
    "fastapi",
    "markdown",
    "pydantic",
    "pydantic-core",
    "pypdf",
    "requests",
    "uvicorn",
    "starlette",
    "anyio",
    "annotated-types",
    "typing-extensions",
    "typing-inspection",
    "certifi",
    "charset-normalizer",
    "idna",
    "urllib3",
    "click",
    "h11",
    "sniffio",
}


def normalized_name(value: str) -> str:
    return re.sub(r"[-_.]+", "-", value).lower()


def metadata_value(metadata: importlib.metadata.PackageMetadata, key: str) -> str:
    value = metadata.get(key)
    return str(value).strip() if value else ""


def package_components() -> list[dict]:
    components = []
    for distribution in importlib.metadata.distributions():
        name = metadata_value(distribution.metadata, "Name")
        normalized = normalized_name(name)
        if normalized not in RUNTIME_PACKAGES:
            continue
        version = distribution.version
        component = {
            "type": "library",
            "name": name,
            "version": version,
            "purl": f"pkg:pypi/{normalized}@{version}",
        }
        license_value = metadata_value(distribution.metadata, "License")
        if license_value and license_value.upper() != "UNKNOWN":
            component["licenses"] = [{"license": {"name": license_value}}]
        homepage = metadata_value(distribution.metadata, "Home-page")
        if homepage:
            component["externalReferences"] = [{"type": "website", "url": homepage}]
        components.append(component)
    return sorted(components, key=lambda item: item["name"].lower())


def generate(bundle_manifest: Path, sbom_path: Path, notices_path: Path) -> None:
    manifest_bytes = bundle_manifest.read_bytes()
    manifest = json.loads(manifest_bytes.decode("utf-8"))
    components = package_components()
    components.insert(
        0,
        {
            "type": "application",
            "name": "zotero-agent-bridge",
            "version": manifest["bridge_version"],
            "properties": [
                {"name": "zab:distribution", "value": manifest["distribution"]},
                {"name": "zab:platform", "value": manifest["platform"]},
                {"name": "zab:architecture", "value": manifest["architecture"]},
                {"name": "zab:bundle-manifest-sha256", "value": hashlib.sha256(manifest_bytes).hexdigest()},
            ],
        },
    )
    sbom = {
        "bomFormat": "CycloneDX",
        "specVersion": "1.5",
        "serialNumber": f"urn:uuid:{hashlib.sha256(manifest_bytes).hexdigest()[:32]}",
        "version": 1,
        "metadata": {
            "timestamp": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
            "component": components[0],
        },
        "components": components[1:],
    }
    sbom_path.write_text(json.dumps(sbom, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    lines = [
        "# Third-Party Notices",
        "",
        "This Beta distribution bundles the following Python runtime dependencies.",
        "The package metadata below is informational; authoritative license texts remain with each upstream project.",
        "",
    ]
    for component in components[1:]:
        licenses = component.get("licenses") or []
        license_name = licenses[0]["license"]["name"] if licenses else "See upstream package metadata"
        homepage = (component.get("externalReferences") or [{}])[0].get("url", "")
        lines.extend(
            [
                f"## {component['name']} {component['version']}",
                "",
                f"- License: {license_name}",
                f"- Package: {component['purl']}",
                *([f"- Website: {homepage}"] if homepage else []),
                "",
            ]
        )
    notices_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"components={len(components)}")
    print(sbom_path)
    print(notices_path)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--bundle-manifest", required=True, type=Path)
    parser.add_argument("--sbom", required=True, type=Path)
    parser.add_argument("--notices", required=True, type=Path)
    args = parser.parse_args()
    generate(args.bundle_manifest, args.sbom, args.notices)


if __name__ == "__main__":
    main()
