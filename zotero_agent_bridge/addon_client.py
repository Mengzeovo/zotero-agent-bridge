from __future__ import annotations

import json
import time
import uuid
from pathlib import Path
from typing import Any

from .errors import BridgeError
from .utils import atomic_write_json, now_iso, read_json


class AddonClient:
    def __init__(
        self,
        *,
        commands_dir: Path,
        responses_dir: Path,
        archive_dir: Path,
        status_path: Path,
        timeout_seconds: float,
        status_ttl_seconds: float,
    ) -> None:
        self.commands_dir = commands_dir
        self.responses_dir = responses_dir
        self.archive_dir = archive_dir
        self.status_path = status_path
        self.timeout_seconds = timeout_seconds
        self.status_ttl_seconds = status_ttl_seconds

    def status(self) -> dict[str, Any]:
        payload = read_json(self.status_path, default={})
        if not payload:
            return {"ready": False, "reason": "missing_status_file"}
        try:
            stale = time.time() - Path(self.status_path).stat().st_mtime > self.status_ttl_seconds
        except OSError:
            stale = True
        payload["fresh"] = not stale
        payload["ready"] = bool(payload.get("ready")) and not stale
        return payload

    def is_ready(self) -> bool:
        return bool(self.status().get("ready"))

    def submit(self, command_type: str, payload: dict[str, Any]) -> dict[str, Any]:
        if not self.is_ready():
            raise BridgeError(503, "addon_unavailable", "Zotero companion add-on is unavailable")
        request_id = uuid.uuid4().hex
        command_file = self.commands_dir / f"{int(time.time() * 1000)}-{request_id}.json"
        response_file = self.responses_dir / f"{request_id}.json"
        command = {
            "request_id": request_id,
            "command": command_type,
            "payload": payload,
            "created_at": now_iso(),
        }
        atomic_write_json(command_file, command)
        deadline = time.time() + self.timeout_seconds
        while time.time() < deadline:
            if response_file.exists():
                response = json.loads(response_file.read_text(encoding="utf-8"))
                archive_path = self.archive_dir / "responses" / response_file.name
                archive_path.parent.mkdir(parents=True, exist_ok=True)
                response_file.replace(archive_path)
                if response.get("ok"):
                    return response["result"]
                error = response.get("error", {})
                error_code = error.get("code", "addon_error")
                status_code = 409 if error_code in {"version_conflict", "collection_conflict"} else 503
                if error_code in {"invalid_request", "invalid_attachment_path", "invalid_parent_collection"}:
                    status_code = 422
                elif error_code in {"item_not_found", "collection_not_found", "parent_collection_not_found"}:
                    status_code = 404
                raise BridgeError(
                    status_code,
                    error_code,
                    error.get("message", "Add-on command failed"),
                    error.get("details") or {},
                )
            time.sleep(0.2)
        raise BridgeError(
            503,
            "addon_timeout",
            "Timed out waiting for Zotero companion add-on response",
            {"command": command_type, "request_id": request_id},
        )

