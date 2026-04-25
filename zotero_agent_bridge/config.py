from __future__ import annotations

import json
import os
import platform
import secrets
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .utils import ensure_dir, read_json


def _default_zotero_data_dir() -> Path:
    home = Path(os.environ.get("USERPROFILE") or Path.home())
    if platform.system() == "Windows":
        return home / "Zotero"
    return home / "Zotero"


def _load_config_file() -> dict[str, Any]:
    config_env = os.environ.get("ZOTERO_AGENT_BRIDGE_CONFIG")
    candidates = [Path(config_env)] if config_env else [Path.cwd() / "zotero_agent_bridge.json"]
    for candidate in candidates:
        if candidate.exists():
            return json.loads(candidate.read_text(encoding="utf-8"))
    return {}


@dataclass(slots=True)
class ObsidianSettings:
    vault_name: str | None = None
    vault_path: Path | None = None
    default_note_dir: str = "Zotero Notes"
    index_path: Path | None = None
    bridge_open_base_url: str | None = None


@dataclass(slots=True)
class Settings:
    host: str
    port: int
    api_token: str
    zotero_local_api_base: str
    bridge_home: Path
    metadata_dir: Path
    notes_dir: Path
    addon_timeout_seconds: float
    addon_status_ttl_seconds: float
    user_agent: str
    base_attachment_path: Path | None = None
    obsidian: ObsidianSettings | None = None

    @classmethod
    def from_env(cls) -> "Settings":
        config = _load_config_file()
        obsidian_config = config.get("obsidian") or {}
        data_dir = Path(
            os.environ.get("ZOTERO_DATA_DIR")
            or config.get("zotero_data_dir")
            or _default_zotero_data_dir()
        )
        bridge_home = Path(
            os.environ.get("ZOTERO_AGENT_BRIDGE_HOME")
            or config.get("bridge_home")
            or data_dir / "zotero-agent-bridge"
        )
        metadata_dir = Path(
            os.environ.get("ZOTERO_AGENT_BRIDGE_METADATA_DIR")
            or config.get("metadata_dir")
            or (Path.cwd() / "metadata" / "zotero_bridge")
        )
        notes_dir = Path(
            os.environ.get("ZOTERO_AGENT_BRIDGE_NOTES_DIR")
            or config.get("notes_dir")
            or (Path.cwd() / "notes" / "zotero_bridge")
        )
        base_attachment = (
            os.environ.get("ZOTERO_AGENT_BRIDGE_BASE_ATTACHMENT_PATH")
            or config.get("base_attachment_path")
        )
        obsidian_vault_path = (
            os.environ.get("ZOTERO_AGENT_BRIDGE_OBSIDIAN_VAULT_PATH")
            or obsidian_config.get("vault_path")
        )
        obsidian_index_path = (
            os.environ.get("ZOTERO_AGENT_BRIDGE_OBSIDIAN_INDEX_PATH")
            or obsidian_config.get("index_path")
        )
        settings = cls(
            host=os.environ.get("ZOTERO_AGENT_BRIDGE_HOST") or config.get("host") or "127.0.0.1",
            port=int(os.environ.get("ZOTERO_AGENT_BRIDGE_PORT") or config.get("port") or 8765),
            api_token=os.environ.get("ZOTERO_AGENT_BRIDGE_TOKEN") or config.get("api_token") or "",
            zotero_local_api_base=(
                os.environ.get("ZOTERO_AGENT_BRIDGE_LOCAL_API_BASE")
                or config.get("zotero_local_api_base")
                or "http://127.0.0.1:23119/api/users/0"
            ),
            bridge_home=bridge_home,
            metadata_dir=metadata_dir,
            notes_dir=notes_dir,
            addon_timeout_seconds=float(
                os.environ.get("ZOTERO_AGENT_BRIDGE_ADDON_TIMEOUT")
                or config.get("addon_timeout_seconds")
                or 30.0
            ),
            addon_status_ttl_seconds=float(
                os.environ.get("ZOTERO_AGENT_BRIDGE_ADDON_STATUS_TTL")
                or config.get("addon_status_ttl_seconds")
                or 15.0
            ),
            user_agent=config.get("user_agent") or "ZoteroAgentBridge/0.1",
            base_attachment_path=Path(base_attachment) if base_attachment else None,
            obsidian=ObsidianSettings(
                vault_name=(
                    os.environ.get("ZOTERO_AGENT_BRIDGE_OBSIDIAN_VAULT_NAME")
                    or obsidian_config.get("vault_name")
                ),
                vault_path=Path(obsidian_vault_path) if obsidian_vault_path else None,
                default_note_dir=(
                    os.environ.get("ZOTERO_AGENT_BRIDGE_OBSIDIAN_DEFAULT_NOTE_DIR")
                    or obsidian_config.get("default_note_dir")
                    or "Zotero Notes"
                ),
                index_path=Path(obsidian_index_path) if obsidian_index_path else None,
                bridge_open_base_url=(
                    os.environ.get("ZOTERO_AGENT_BRIDGE_OBSIDIAN_BRIDGE_OPEN_BASE_URL")
                    or obsidian_config.get("bridge_open_base_url")
                ),
            ),
        )
        settings.prepare_runtime()
        return settings

    @property
    def commands_dir(self) -> Path:
        return self.bridge_home / "commands"

    @property
    def responses_dir(self) -> Path:
        return self.bridge_home / "responses"

    @property
    def archive_dir(self) -> Path:
        return self.bridge_home / "archive"

    @property
    def logs_dir(self) -> Path:
        return self.bridge_home / "logs"

    @property
    def status_dir(self) -> Path:
        return self.bridge_home / "status"

    @property
    def addon_status_path(self) -> Path:
        return self.status_dir / "addon-status.json"

    @property
    def operations_log_path(self) -> Path:
        return self.logs_dir / "operations.jsonl"

    @property
    def generated_config_path(self) -> Path:
        return self.bridge_home / "bridge.generated.json"

    def prepare_runtime(self) -> None:
        if self.obsidian and self.obsidian.index_path is None:
            self.obsidian.index_path = self.metadata_dir / "obsidian-index.json"
        for directory in [
            self.bridge_home,
            self.commands_dir,
            self.responses_dir,
            self.archive_dir,
            self.logs_dir,
            self.status_dir,
            self.metadata_dir,
            self.notes_dir,
        ]:
            ensure_dir(directory)
        if self.obsidian and self.obsidian.index_path:
            ensure_dir(self.obsidian.index_path.parent)
        if not self.api_token:
            persisted = read_json(self.generated_config_path, default={})
            token = persisted.get("api_token")
            if not token:
                token = secrets.token_hex(24)
                self.generated_config_path.write_text(
                    json.dumps({"api_token": token}, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
            self.api_token = token
        else:
            persisted = read_json(self.generated_config_path, default={})
            if persisted.get("api_token") != self.api_token:
                self.generated_config_path.write_text(
                    json.dumps({"api_token": self.api_token}, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
