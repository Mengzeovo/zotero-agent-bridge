from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import subprocess
import tempfile
import unittest
import zipfile
from pathlib import Path

from zotero_agent_bridge.runtime_paths import resource_path
from zotero_agent_bridge.version import BRIDGE_VERSION, LIFECYCLE_PROTOCOL_VERSION


ROOT = Path(__file__).resolve().parents[1]
BUNDLE_ROOT = ROOT / "dist" / "bridge" / "windows-x64" / "0.3.3"
XPI = ROOT / "dist" / "zotero-agent-bridge-addon-0.3.3.xpi"
TEST_RUNTIME = ROOT / "tmp" / "test-runtime"


def load_script(name: str, relative: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class BundlePackagingTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        TEST_RUNTIME.mkdir(parents=True, exist_ok=True)

    def test_runtime_version_and_source_resource(self) -> None:
        self.assertEqual(BRIDGE_VERSION, "0.3.3")
        self.assertEqual(LIFECYCLE_PROTOCOL_VERSION, 1)
        self.assertTrue(resource_path("config", "literature-assistant.md").is_file())

    def test_bundle_manifest_covers_exact_file_set_and_hashes(self) -> None:
        manifest = json.loads((BUNDLE_ROOT / "bridge-manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["bundle_schema_version"], 1)
        self.assertEqual(manifest["bridge_version"], "0.3.3")
        self.assertEqual(manifest["protocol_version"], 1)
        self.assertEqual(manifest["distribution"], "xpi-bundled")
        records = {record["path"]: record for record in manifest["files"]}
        actual = {
            f"zab-bridge/{path.relative_to(BUNDLE_ROOT / 'zab-bridge').as_posix()}"
            for path in (BUNDLE_ROOT / "zab-bridge").rglob("*")
            if path.is_file()
        }
        self.assertEqual(set(records), actual)
        self.assertIn(manifest["entrypoint"], records)
        for relative, record in records.items():
            path = BUNDLE_ROOT / relative
            self.assertEqual(path.stat().st_size, record["size"], relative)
            self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), record["sha256"], relative)

    def test_xpi_contains_verified_bundle_and_supply_chain_metadata(self) -> None:
        with zipfile.ZipFile(XPI) as archive:
            names = set(archive.namelist())
            self.assertIn("bridge/windows-x64/zab-bridge/zab-bridge.exe", names)
            self.assertIn("bridge/windows-x64/SBOM.cdx.json", names)
            self.assertIn("bridge/windows-x64/THIRD_PARTY_NOTICES.md", names)
            manifest = json.loads(archive.read("bridge/windows-x64/bridge-manifest.json"))
            for record in manifest["files"]:
                payload = archive.read(f"bridge/windows-x64/{record['path']}")
                self.assertEqual(len(payload), record["size"])
                self.assertEqual(hashlib.sha256(payload).hexdigest(), record["sha256"])

    def test_xpi_builder_rejects_tampered_bundle(self) -> None:
        builder = load_script("zab_build_xpi_test", "packaging/build_xpi.py")
        with tempfile.TemporaryDirectory(prefix="bundle-tamper-", dir=TEST_RUNTIME) as directory:
            root = Path(directory)
            bundle = root / "bundle"
            (bundle / "zab-bridge").mkdir(parents=True)
            executable = bundle / "zab-bridge" / "zab-bridge.exe"
            executable.write_bytes(b"good")
            manifest = {
                "bundle_schema_version": 1,
                "bridge_version": "0.3.3",
                "protocol_version": 1,
                "distribution": "xpi-bundled",
                "platform": "windows",
                "architecture": "x64",
                "entrypoint": "zab-bridge/zab-bridge.exe",
                "sentinel": ".zab-bundle-installed.json",
                "build": {},
                "files": [{
                    "path": "zab-bridge/zab-bridge.exe",
                    "size": 4,
                    "sha256": hashlib.sha256(b"good").hexdigest(),
                }],
            }
            (bundle / "bridge-manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
            executable.write_bytes(b"evil")
            with self.assertRaisesRegex(ValueError, "verification failed"):
                builder.load_and_verify_bundle(bundle)

    def test_bundle_and_config_manager_pure_logic_runs_in_node(self) -> None:
        script = r"""
const assert = require('assert');
const path = require('path');
const bundle = require('./zotero_companion_addon/chrome/content/scripts/bridge_bundle_manager.js').__test;
const config = require('./zotero_companion_addon/chrome/content/scripts/bridge_config_manager.js').__test;
const manifest = {
  bundle_schema_version: 1, bridge_version: '0.3.3', protocol_version: 1,
  distribution: 'xpi-bundled', platform: 'windows', architecture: 'x64',
  entrypoint: 'zab-bridge/zab-bridge.exe', sentinel: '.zab-bundle-installed.json',
  files: [{path:'zab-bridge/zab-bridge.exe',size:1,sha256:'a'.repeat(64)}]
};
assert.strictEqual(bundle.validateManifest(manifest).bridge_version, '0.3.3');
assert.throws(() => bundle.normalizeManifestPath('../escape'));
const P = {
  isAbsolute:path.win32.isAbsolute,
  normalize:path.win32.normalize,
  join:path.win32.join,
  parent:path.win32.dirname
};
assert.strictEqual(bundle.pathInside('C:/safe', 'C:/unsafe/x.exe', P), false);
assert.strictEqual(config.loopbackHost('0.0.0.0'), '127.0.0.1');
assert.strictEqual(config.legacyWorkdir({workdir:'D:/repo'}, P), path.win32.normalize('D:/repo'));
assert.strictEqual(config.legacyWorkdir({workdir:'relative'}, P), null);
const migrated = config.migrateConfig({metadata_dir:'./mirror/meta',pi:{session_dir:'./sessions'}}, {
  bridgeHome:'D:/bridge',zoteroDataDir:'D:/zotero',legacyBaseDir:'D:/old',PathUtils:P
});
assert.strictEqual(migrated.bridge_home, 'D:/bridge');
assert.strictEqual(migrated.metadata_dir, path.win32.normalize('D:/old/mirror/meta'));
assert.strictEqual(config.resolveOptionalPath('../shared/data', 'D:/old/config', P), path.win32.normalize('D:/old/shared/data'));
assert.strictEqual(config.resolveOptionalPath('E:/papers', 'D:/old/config', P), path.win32.normalize('E:/papers'));
assert.strictEqual(config.resolveOptionalPath('C:/Users/test/sessions', 'D:/old/config', P), path.win32.normalize('C:/Users/test/sessions'));
"""
        result = subprocess.run(["node", "-e", script], cwd=ROOT, capture_output=True, text=True, check=False)
        self.assertEqual(result.returncode, 0, result.stderr or result.stdout)

    def test_release_scan_rejects_no_machine_paths_or_tokens(self) -> None:
        result = subprocess.run(
            [
                "py.exe", "-3.12", str(ROOT / "packaging" / "scan_release.py"), str(XPI),
                "--forbid", str(ROOT), "--forbid", str(Path.home()),
            ],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr or result.stdout)
        self.assertIn("Release scan passed", result.stdout)


if __name__ == "__main__":
    unittest.main()
