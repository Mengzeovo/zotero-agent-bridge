from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import tempfile
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REGISTER = ROOT / "scripts" / "register_bridge_launcher.ps1"
LAUNCH = ROOT / "scripts" / "launch_bridge_detached.ps1"
SPAWNER = ROOT / "scripts" / "spawn_bridge_detached.py"


@unittest.skipUnless(os.name == "nt", "Windows launcher tests require Windows")
class WindowsBridgeLauncherTest(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path(tempfile.mkdtemp(prefix="zab-launcher-"))
        self.bridge_home = self.root / "bridge home"
        self.config_path = self.root / "bridge config.json"
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            self.port = probe.getsockname()[1]
        self.config_path.write_text(
            json.dumps(
                {
                    "host": "127.0.0.1",
                    "port": self.port,
                    "zotero_local_api_base": "http://127.0.0.1:9/api/users/0",
                    "bridge_home": str(self.bridge_home),
                    "metadata_dir": str(self.root / "metadata"),
                    "notes_dir": str(self.root / "notes"),
                    "addon_status_ttl_seconds": 60,
                    "lifecycle_addon_exit_grace_seconds": 5,
                }
            ),
            encoding="utf-8-sig",
        )
        status_dir = self.bridge_home / "status"
        status_dir.mkdir(parents=True)
        (status_dir / "addon-status.json").write_text(
            json.dumps({"ready": True, "last_seen": "test"}),
            encoding="utf-8",
        )
        self.token: str | None = None

    def tearDown(self) -> None:
        if self.token:
            try:
                self._request(
                    "POST",
                    "/lifecycle/shutdown",
                    owner_token="owner-secret",
                    timeout=1,
                )
            except Exception:
                pass
        deadline = time.time() + 5
        while time.time() < deadline and self._port_open():
            time.sleep(0.1)
        shutil.rmtree(self.root, ignore_errors=True)

    def _powershell(self, script: Path, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [
                "powershell.exe",
                "-NoProfile",
                "-NonInteractive",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(script),
                *args,
            ],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )

    def _port_open(self) -> bool:
        try:
            with socket.create_connection(("127.0.0.1", self.port), timeout=0.2):
                return True
        except OSError:
            return False

    def _request(
        self,
        method: str,
        path: str,
        *,
        owner_token: str | None = None,
        timeout: float = 3,
    ) -> dict:
        headers = {"X-Bridge-Token": str(self.token)}
        if owner_token:
            headers["X-Bridge-Owner-Token"] = owner_token
        request = urllib.request.Request(
            f"http://127.0.0.1:{self.port}{path}",
            method=method,
            headers=headers,
            data=b"{}" if method == "POST" else None,
        )
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.load(response)

    def test_detached_spawner_breaks_away_from_zotero_job(self) -> None:
        launcher = LAUNCH.read_text(encoding="utf-8-sig")
        spawner = SPAWNER.read_text(encoding="utf-8")
        self.assertIn("spawn_bridge_detached.py", launcher)
        self.assertIn("CREATE_BREAKAWAY_FROM_JOB", spawner)
        self.assertIn("subprocess.DETACHED_PROCESS", spawner)
        self.assertIn("subprocess.CREATE_NEW_PROCESS_GROUP", spawner)

    def test_registration_writes_valid_absolute_descriptor(self) -> None:
        result = self._powershell(REGISTER, "-ConfigPath", str(self.config_path))
        self.assertEqual(result.returncode, 0, result.stderr or result.stdout)
        descriptor = json.loads((self.bridge_home / "bridge-launcher.json").read_text(encoding="utf-8"))
        self.assertEqual(descriptor["schema_version"], 1)
        self.assertEqual(descriptor["platform"], "windows")
        self.assertTrue(Path(descriptor["command"]).is_absolute())
        self.assertTrue(Path(descriptor["workdir"]).is_absolute())
        self.assertIn(str(LAUNCH), descriptor["arguments"])
        self.assertEqual(descriptor["owner_arguments"]["token"], "-OwnerToken")

    def test_launcher_is_idempotent_and_owner_controls_shutdown(self) -> None:
        first = self._powershell(
            LAUNCH,
            "-ConfigPath", str(self.config_path),
            "-OwnerId", "owner-one",
            "-OwnerToken", "owner-secret",
            "-ReadyTimeoutSeconds", "20",
        )
        self.assertEqual(first.returncode, 0, first.stderr or first.stdout)
        token_path = self.bridge_home / "bridge.generated.json"
        self.token = json.loads(token_path.read_text(encoding="utf-8"))["api_token"]
        health = self._request("GET", "/health")
        self.assertTrue(health["lifecycle"]["managed"])
        self.assertEqual(health["lifecycle"]["owner_id"], "owner-one")

        second = self._powershell(
            LAUNCH,
            "-ConfigPath", str(self.config_path),
            "-OwnerId", "owner-two",
            "-OwnerToken", "other-secret",
            "-ReadyTimeoutSeconds", "10",
        )
        self.assertEqual(second.returncode, 0, second.stderr or second.stdout)
        self.assertEqual(self._request("GET", "/lifecycle")["owner_id"], "owner-one")

        with self.assertRaises(urllib.error.HTTPError) as rejected:
            self._request("POST", "/lifecycle/shutdown", owner_token="other-secret")
        self.assertEqual(rejected.exception.code, 403)
        accepted = self._request("POST", "/lifecycle/shutdown", owner_token="owner-secret")
        self.assertEqual(accepted["status"], "shutting_down")
        deadline = time.time() + 10
        while time.time() < deadline and self._port_open():
            time.sleep(0.1)
        self.assertFalse(self._port_open())
        self.token = None


if __name__ == "__main__":
    unittest.main()
