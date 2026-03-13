from __future__ import annotations

import json
import os
import queue
import re
import subprocess
import sys
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
import tkinter as tk
from tkinter import messagebox, ttk

import requests


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG_PATH = PROJECT_ROOT / 'config' / 'bridge-config.json'
RUNTIME_DIR = PROJECT_ROOT / 'tmp' / 'bridge_panel'
LOG_DIR = RUNTIME_DIR / 'logs'
MCP_ENTRYPOINT = PROJECT_ROOT / 'scripts' / 'run_mcp.py'
CODEX_PYTHON = Path(sys.executable).resolve()
CODEX_SERVER_NAME = 'zotero-agent-bridge'


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def parse_iso_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        normalized = value.replace('Z', '+00:00')
        return datetime.fromisoformat(normalized)
    except ValueError:
        return None


def toml_literal_string(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


@dataclass(slots=True)
class PanelConfig:
    path: Path
    payload: dict[str, object]

    @classmethod
    def load(cls, path: Path) -> 'PanelConfig':
        data = json.loads(path.read_text(encoding='utf-8-sig'))
        return cls(path=path, payload=data)

    @property
    def host(self) -> str:
        return str(self.payload.get('host') or '127.0.0.1')

    @property
    def port(self) -> int:
        return int(self.payload.get('port') or 8765)

    @property
    def base_url(self) -> str:
        return f'http://{self.host}:{self.port}'

    @property
    def local_api_base(self) -> str:
        return str(self.payload.get('zotero_local_api_base') or 'http://127.0.0.1:23119/api/users/0')

    @property
    def bridge_home(self) -> Path:
        return Path(str(self.payload.get('bridge_home') or '')).expanduser()

    @property
    def addon_status_ttl_seconds(self) -> float:
        return float(self.payload.get('addon_status_ttl_seconds') or 15.0)

    @property
    def api_token(self) -> str | None:
        token = self.payload.get('api_token')
        return str(token) if token else None

    @property
    def token_path(self) -> Path:
        return self.bridge_home / 'bridge.generated.json'

    @property
    def addon_status_path(self) -> Path:
        return self.bridge_home / 'status' / 'addon-status.json'


class StatusRow:
    def __init__(self, parent: ttk.Frame, row: int, title: str) -> None:
        self.indicator = tk.Label(parent, width=2, relief='groove', bg='#808080')
        self.indicator.grid(row=row, column=0, padx=(0, 8), pady=4, sticky='w')

        self.title = ttk.Label(parent, text=title, width=18)
        self.title.grid(row=row, column=1, padx=(0, 8), pady=4, sticky='w')

        self.value_var = tk.StringVar(value='Checking...')
        self.value = ttk.Label(parent, textvariable=self.value_var)
        self.value.grid(row=row, column=2, padx=(0, 8), pady=4, sticky='w')

    def set(self, level: str, text: str) -> None:
        color_map = {
            'ok': '#2e8b57',
            'warn': '#d4a017',
            'error': '#b22222',
            'info': '#4682b4',
        }
        self.indicator.configure(bg=color_map.get(level, '#808080'))
        self.value_var.set(text)


class BridgePanelApp:
    def __init__(self, root: tk.Tk, config_path: Path) -> None:
        self.root = root
        self.config_path = config_path
        self.config = PanelConfig.load(config_path)
        self.bridge_process: subprocess.Popen[str] | None = None
        self.bridge_stdout_handle = None
        self.bridge_stderr_handle = None
        self.last_bridge_exit_code: int | None = None
        self.auto_refresh_ms = 5000
        self._refresh_job: str | None = None
        self._ui_pump_job: str | None = None
        self._refresh_in_progress = False
        self._refresh_pending = False
        self._refresh_pending_reschedule = False
        self._codex_task_in_progress = False
        self._closing = False
        self._ui_queue: queue.SimpleQueue[tuple[Callable[..., None], tuple[object, ...]]] = queue.SimpleQueue()

        self.root.title('Zotero Agent Bridge Panel')
        self.root.geometry('780x500')
        self.root.minsize(720, 430)
        self.root.protocol('WM_DELETE_WINDOW', self.on_close)

        self.message_var = tk.StringVar(value='Ready')
        self.last_refresh_var = tk.StringVar(value='Never')

        self._build_ui()
        self._ui_pump_job = self.root.after(50, self._pump_ui_queue)
        self._schedule_refresh(50)

    def _build_ui(self) -> None:
        container = ttk.Frame(self.root, padding=14)
        container.pack(fill='both', expand=True)

        header = ttk.Frame(container)
        header.pack(fill='x')
        ttk.Label(header, text='Zotero Agent Bridge', font=('Segoe UI', 16, 'bold')).pack(anchor='w')
        ttk.Label(
            header,
            text='Use this panel to start the local bridge and see whether Zotero, the add-on, and the HTTP service are healthy.',
            wraplength=700,
        ).pack(anchor='w', pady=(6, 0))

        meta = ttk.Frame(container, padding=(0, 12, 0, 0))
        meta.pack(fill='x')
        ttk.Label(meta, text=f'Config: {self.config.path}').pack(anchor='w')
        ttk.Label(meta, text=f'Bridge home: {self.config.bridge_home}').pack(anchor='w', pady=(4, 0))
        ttk.Label(meta, text=f'MCP entrypoint: {MCP_ENTRYPOINT}').pack(anchor='w', pady=(4, 0))

        status_frame = ttk.LabelFrame(container, text='Status', padding=12)
        status_frame.pack(fill='x', pady=(14, 0))
        status_frame.columnconfigure(2, weight=1)

        self.status_rows = {
            'managed_process': StatusRow(status_frame, 0, 'Managed bridge'),
            'local_api': StatusRow(status_frame, 1, 'Zotero Local API'),
            'addon': StatusRow(status_frame, 2, 'Companion add-on'),
            'bridge': StatusRow(status_frame, 3, 'Bridge HTTP'),
            'capabilities': StatusRow(status_frame, 4, 'Read / Write'),
            'token': StatusRow(status_frame, 5, 'Bridge token'),
            'codex': StatusRow(status_frame, 6, 'Codex MCP'),
        }

        controls = ttk.Frame(container)
        controls.pack(fill='x', pady=(14, 0))

        bridge_buttons = ttk.Frame(controls)
        bridge_buttons.pack(fill='x')
        ttk.Button(bridge_buttons, text='Start Bridge', command=self.start_bridge).pack(side='left')
        ttk.Button(bridge_buttons, text='Stop Bridge', command=self.stop_bridge).pack(side='left', padx=(8, 0))
        ttk.Button(bridge_buttons, text='Refresh', command=self.refresh_status).pack(side='left', padx=(8, 0))
        ttk.Button(bridge_buttons, text='Open Config', command=self.open_config).pack(side='left', padx=(20, 0))
        ttk.Button(bridge_buttons, text='Open Bridge Home', command=self.open_bridge_home).pack(side='left', padx=(8, 0))

        codex_buttons = ttk.Frame(controls)
        codex_buttons.pack(fill='x', pady=(8, 0))
        ttk.Button(codex_buttons, text='Open Codex Config', command=self.open_codex_config).pack(side='left')
        ttk.Button(codex_buttons, text='Register Codex', command=self.register_codex).pack(side='left', padx=(8, 0))
        ttk.Button(codex_buttons, text='Copy Codex Setup', command=self.copy_codex_setup).pack(side='left', padx=(8, 0))

        info_frame = ttk.LabelFrame(container, text='Agent Integration', padding=12)
        info_frame.pack(fill='both', expand=True, pady=(14, 0))
        ttk.Label(
            info_frame,
            text='Start the HTTP bridge here. For Codex, register the stdio MCP once, then Codex will launch it automatically when a session needs Zotero tools.',
            wraplength=700,
        ).pack(anchor='w')

        self.integration_text = tk.Text(info_frame, height=10, wrap='word')
        self.integration_text.pack(fill='both', expand=True, pady=(10, 0))
        self.integration_text.insert('1.0', self.build_codex_setup_text())
        self.integration_text.configure(state='disabled')

        footer = ttk.Frame(container)
        footer.pack(fill='x', pady=(12, 0))
        ttk.Label(footer, textvariable=self.message_var).pack(side='left')
        ttk.Label(footer, textvariable=self.last_refresh_var).pack(side='right')

    def codex_config_path(self) -> Path:
        return Path.home() / '.codex' / 'config.toml'

    def build_codex_add_command(self) -> str:
        return f'codex mcp add {CODEX_SERVER_NAME} -- "{CODEX_PYTHON}" "{MCP_ENTRYPOINT}"'

    def build_codex_toml(self) -> str:
        return '\n'.join(
            [
                f'[mcp_servers.{CODEX_SERVER_NAME}]',
                f'command = {toml_literal_string(str(CODEX_PYTHON))}',
                f'args = [{toml_literal_string(str(MCP_ENTRYPOINT))}]',
                f'cwd = {toml_literal_string(str(PROJECT_ROOT))}',
                'startup_timeout_sec = 30',
                "env = { PYTHONUTF8 = '1' }",
            ]
        )

    def build_codex_setup_text(self) -> str:
        return '\n'.join(
            [
                'Bootstrap Codex registration command:',
                self.build_codex_add_command(),
                '',
                f'Then ensure {self.codex_config_path()} contains this section:',
                self.build_codex_toml(),
                '',
                'After this, keep the HTTP bridge running from this panel before using Zotero tools in Codex.',
            ]
        )

    def token(self) -> str | None:
        if self.config.api_token:
            return self.config.api_token
        if not self.config.token_path.exists():
            return None
        try:
            payload = json.loads(self.config.token_path.read_text(encoding='utf-8-sig'))
        except (OSError, json.JSONDecodeError):
            return None
        token = payload.get('api_token')
        return str(token) if token else None

    def managed_bridge_running(self) -> bool:
        return self.bridge_process is not None and self.bridge_process.poll() is None

    def _enqueue_ui_call(self, callback: Callable[..., None], *args: object) -> None:
        if self._closing:
            return
        self._ui_queue.put((callback, args))

    def _cancel_ui_pump_job(self) -> None:
        if self._ui_pump_job:
            try:
                self.root.after_cancel(self._ui_pump_job)
            except (ValueError, tk.TclError):
                pass
            self._ui_pump_job = None

    def _pump_ui_queue(self) -> None:
        self._ui_pump_job = None

        while True:
            try:
                callback, args = self._ui_queue.get_nowait()
            except queue.Empty:
                break
            callback(*args)

        if not self._closing:
            self._ui_pump_job = self.root.after(50, self._pump_ui_queue)

    def _cancel_refresh_job(self) -> None:
        if self._refresh_job:
            try:
                self.root.after_cancel(self._refresh_job)
            except (ValueError, tk.TclError):
                pass
            self._refresh_job = None

    def _schedule_refresh(self, delay_ms: int | None = None) -> None:
        if self._closing:
            return
        self._cancel_refresh_job()
        self._refresh_job = self.root.after(delay_ms or self.auto_refresh_ms, self.refresh_status)

    def _sync_managed_process_status(self) -> None:
        if self.bridge_process is not None and self.bridge_process.poll() is not None:
            exit_code = self.bridge_process.returncode
            self.bridge_process = None
            self._close_bridge_logs()
            if exit_code != self.last_bridge_exit_code:
                self.last_bridge_exit_code = exit_code
                self.set_message(f'Managed bridge exited with code {exit_code}. Check logs in {LOG_DIR}.')

        managed_running = self.managed_bridge_running()
        self.status_rows['managed_process'].set(
            'ok' if managed_running else 'info',
            'Running in this panel' if managed_running else 'Not managed by this panel',
        )

    def start_bridge(self) -> None:
        if self.managed_bridge_running():
            self.set_message('Bridge is already running from this panel.')
            return

        bridge_status = self.fetch_bridge_status()
        if bridge_status['ok']:
            self.set_message('Bridge already responds on the configured port. Not starting a duplicate process.')
            self.refresh_status()
            return

        LOG_DIR.mkdir(parents=True, exist_ok=True)
        stdout_path = LOG_DIR / 'bridge.stdout.log'
        stderr_path = LOG_DIR / 'bridge.stderr.log'
        self.bridge_stdout_handle = stdout_path.open('a', encoding='utf-8')
        self.bridge_stderr_handle = stderr_path.open('a', encoding='utf-8')

        env = os.environ.copy()
        env['ZOTERO_AGENT_BRIDGE_CONFIG'] = str(self.config.path)
        env['PYTHONUNBUFFERED'] = '1'

        creationflags = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
        self.last_bridge_exit_code = None
        self.bridge_process = subprocess.Popen(
            [sys.executable, '-m', 'zotero_agent_bridge'],
            cwd=str(PROJECT_ROOT),
            env=env,
            stdout=self.bridge_stdout_handle,
            stderr=self.bridge_stderr_handle,
            text=True,
            creationflags=creationflags,
        )
        self.set_message('Bridge process started. Waiting for health checks to turn green...')
        self.root.after(700, self.refresh_status)

    def stop_bridge(self) -> None:
        if not self.managed_bridge_running():
            self.set_message('No bridge process from this panel is currently running.')
            self._close_bridge_logs()
            self.refresh_status()
            return

        assert self.bridge_process is not None
        self.bridge_process.terminate()
        try:
            self.bridge_process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            self.bridge_process.kill()
            self.bridge_process.wait(timeout=5)
        finally:
            self.bridge_process = None
            self._close_bridge_logs()
        self.set_message('Bridge process stopped.')
        self.refresh_status()

    def _close_bridge_logs(self) -> None:
        for handle_name in ('bridge_stdout_handle', 'bridge_stderr_handle'):
            handle = getattr(self, handle_name)
            if handle:
                handle.close()
                setattr(self, handle_name, None)

    def fetch_local_api_status(self, session: requests.Session | None = None) -> dict[str, object]:
        url = f"{self.config.local_api_base.rstrip('/')}/items"
        client = session or requests
        try:
            response = client.get(url, params={'limit': 1}, timeout=3)
            response.raise_for_status()
            return {'ok': True, 'text': 'Reachable'}
        except requests.RequestException as exc:
            return {'ok': False, 'text': f'Unavailable: {exc.__class__.__name__}'}

    def fetch_addon_status(self) -> dict[str, object]:
        path = self.config.addon_status_path
        if not path.exists():
            return {'ok': False, 'text': 'Missing heartbeat file'}
        try:
            payload = json.loads(path.read_text(encoding='utf-8-sig'))
        except (OSError, json.JSONDecodeError):
            return {'ok': False, 'text': 'Unreadable heartbeat JSON'}

        last_seen = parse_iso_datetime(payload.get('last_seen'))
        fresh = False
        if last_seen is not None:
            fresh = (now_utc() - last_seen).total_seconds() <= self.config.addon_status_ttl_seconds
        ready = bool(payload.get('ready')) and fresh
        version = payload.get('addon_version') or 'unknown'
        if ready:
            return {'ok': True, 'text': f'Ready ({version})'}
        if payload.get('ready'):
            return {'ok': False, 'text': f'Stale heartbeat ({version})'}
        return {'ok': False, 'text': f'Reported not ready ({version})'}

    def fetch_bridge_status(
        self,
        token: str | None = None,
        session: requests.Session | None = None,
    ) -> dict[str, object]:
        token = token if token is not None else self.token()
        if not token:
            return {'ok': False, 'text': 'No bridge token yet'}
        client = session or requests
        try:
            response = client.get(
                f'{self.config.base_url}/health',
                headers={'X-Bridge-Token': token},
                timeout=3,
            )
            response.raise_for_status()
            return {'ok': True, 'text': 'HTTP bridge responding', 'payload': response.json()}
        except requests.RequestException as exc:
            return {'ok': False, 'text': f'Down: {exc.__class__.__name__}'}

    def fetch_capabilities_status(
        self,
        token: str | None = None,
        session: requests.Session | None = None,
    ) -> dict[str, object]:
        token = token if token is not None else self.token()
        if not token:
            return {'ok': False, 'text': 'Token missing'}
        client = session or requests
        try:
            response = client.get(
                f'{self.config.base_url}/capabilities',
                headers={'X-Bridge-Token': token},
                timeout=3,
            )
            response.raise_for_status()
            payload = response.json()
            read_ok = bool(payload.get('read'))
            write_ok = bool(payload.get('write'))
            status_text = f'read={str(read_ok).lower()} write={str(write_ok).lower()}'
            return {'ok': read_ok and write_ok, 'text': status_text}
        except requests.RequestException as exc:
            return {'ok': False, 'text': f'Unavailable: {exc.__class__.__name__}'}

    def fetch_codex_status(self) -> dict[str, object]:
        config_path = self.codex_config_path()
        if not config_path.exists():
            return {'ok': False, 'text': f'Missing: {config_path}'}
        try:
            content = config_path.read_text(encoding='utf-8-sig')
        except OSError:
            return {'ok': False, 'text': f'Unreadable: {config_path}'}

        marker = f'[mcp_servers.{CODEX_SERVER_NAME}]'
        if marker in content:
            return {'ok': True, 'text': f'Registered: {config_path}'}
        return {'ok': False, 'text': f'Not registered: {config_path}'}

    def _collect_refresh_snapshot(self) -> dict[str, object]:
        token = self.token()
        with requests.Session() as session:
            local_api = self.fetch_local_api_status(session=session)
            addon = self.fetch_addon_status()
            bridge = self.fetch_bridge_status(token=token, session=session)
            capabilities = self.fetch_capabilities_status(token=token, session=session)

        bridge_level = 'ok' if bridge['ok'] else ('warn' if token else 'error')
        capability_level = 'ok' if capabilities['ok'] else ('warn' if bridge['ok'] else 'error')
        token_text = f'Present: {self.config.token_path}' if token else f'Missing: {self.config.token_path}'
        codex = self.fetch_codex_status()
        codex_level = 'ok' if codex['ok'] else ('error' if 'Unreadable' in str(codex['text']) else 'warn')

        return {
            'local_api': {'level': 'ok' if local_api['ok'] else 'error', 'text': str(local_api['text'])},
            'addon': {'level': 'ok' if addon['ok'] else 'error', 'text': str(addon['text'])},
            'bridge': {'level': bridge_level, 'text': str(bridge['text'])},
            'capabilities': {'level': capability_level, 'text': str(capabilities['text'])},
            'token': {'level': 'ok' if token else 'warn', 'text': token_text},
            'codex': {'level': codex_level, 'text': str(codex['text'])},
            'last_refresh': f"Last refresh: {time.strftime('%H:%M:%S')}",
        }

    def _refresh_status_worker(self, reschedule: bool) -> None:
        try:
            snapshot = self._collect_refresh_snapshot()
        except Exception as exc:  # pragma: no cover - defensive guard for UI thread stability
            snapshot = {'message': f'Refresh failed: {exc.__class__.__name__}'}
        self._enqueue_ui_call(self._apply_refresh_snapshot, snapshot, reschedule)

    def _apply_refresh_snapshot(self, snapshot: dict[str, object], reschedule: bool) -> None:
        self._refresh_in_progress = False
        if self._closing:
            return

        self._sync_managed_process_status()

        for row_name in ('local_api', 'addon', 'bridge', 'capabilities', 'token', 'codex'):
            payload = snapshot.get(row_name)
            if isinstance(payload, dict):
                self.status_rows[row_name].set(str(payload['level']), str(payload['text']))

        last_refresh = snapshot.get('last_refresh')
        if isinstance(last_refresh, str):
            self.last_refresh_var.set(last_refresh)

        message = snapshot.get('message')
        if isinstance(message, str):
            self.set_message(message)

        pending = self._refresh_pending
        pending_reschedule = self._refresh_pending_reschedule
        self._refresh_pending = False
        self._refresh_pending_reschedule = False

        if pending:
            self.refresh_status(reschedule=pending_reschedule)
            return

        if reschedule:
            self._schedule_refresh()

    def refresh_status(self, *, reschedule: bool = True) -> None:
        if self._closing:
            return

        self._cancel_refresh_job()
        self._sync_managed_process_status()

        if self._refresh_in_progress:
            self._refresh_pending = True
            self._refresh_pending_reschedule = self._refresh_pending_reschedule or reschedule
            return

        self._refresh_in_progress = True
        threading.Thread(
            target=self._refresh_status_worker,
            args=(reschedule,),
            name='bridge-panel-refresh',
            daemon=True,
        ).start()

    def set_message(self, text: str) -> None:
        self.message_var.set(text)

    def open_config(self) -> None:
        os.startfile(self.config.path)  # type: ignore[attr-defined]

    def open_bridge_home(self) -> None:
        self.config.bridge_home.mkdir(parents=True, exist_ok=True)
        os.startfile(self.config.bridge_home)  # type: ignore[attr-defined]

    def open_codex_config(self) -> None:
        config_path = self.codex_config_path()
        config_path.parent.mkdir(parents=True, exist_ok=True)
        if not config_path.exists():
            config_path.touch()
        os.startfile(config_path)  # type: ignore[attr-defined]

    def sync_codex_config(self) -> None:
        config_path = self.codex_config_path()
        config_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            content = config_path.read_text(encoding='utf-8-sig') if config_path.exists() else ''
        except OSError as exc:
            raise RuntimeError(f'Failed to read {config_path}: {exc}') from exc

        section = self.build_codex_toml().strip()
        pattern = re.compile(
            rf'(?ms)^\[mcp_servers\.{re.escape(CODEX_SERVER_NAME)}\]\n.*?(?=^\[|\Z)'
        )
        if pattern.search(content):
            updated = pattern.sub(section + '\n', content, count=1)
        else:
            normalized = content.rstrip()
            separator = '\n\n' if normalized else ''
            updated = f'{normalized}{separator}{section}\n'

        if updated == content:
            return

        try:
            config_path.write_text(updated, encoding='utf-8')
        except OSError as exc:
            raise RuntimeError(f'Failed to write {config_path}: {exc}') from exc

    def run_codex_cli(self, *args: str) -> subprocess.CompletedProcess[str]:
        creationflags = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
        return subprocess.run(
            ['cmd', '/c', 'codex', *args],
            cwd=str(PROJECT_ROOT),
            capture_output=True,
            text=True,
            creationflags=creationflags,
        )

    def _register_codex_worker(self) -> None:
        try:
            existing = self.run_codex_cli('mcp', 'get', CODEX_SERVER_NAME, '--json')
            if existing.returncode == 0:
                self.sync_codex_config()
                result = {'status': 'synced'}
            else:
                created = self.run_codex_cli(
                    'mcp',
                    'add',
                    CODEX_SERVER_NAME,
                    '--',
                    str(CODEX_PYTHON),
                    str(MCP_ENTRYPOINT),
                )
                if created.returncode != 0:
                    detail = (created.stderr or created.stdout or 'Unknown error').strip()
                    result = {'status': 'error', 'detail': detail}
                else:
                    self.sync_codex_config()
                    result = {'status': 'created'}
        except Exception as exc:  # pragma: no cover - defensive guard for UI thread stability
            result = {'status': 'error', 'detail': f'{exc.__class__.__name__}: {exc}'}

        self._enqueue_ui_call(self._finish_register_codex, result)

    def _finish_register_codex(self, result: dict[str, str]) -> None:
        self._codex_task_in_progress = False
        if self._closing:
            return

        status = result.get('status')
        if status == 'synced':
            self.set_message('Codex MCP config synced.')
            self.refresh_status()
            return

        if status == 'error':
            detail = result.get('detail') or 'Unknown error'
            messagebox.showerror('Codex Registration Failed', detail)
            self.set_message('Codex MCP registration failed.')
            return

        self.set_message('Codex MCP registered.')
        self.refresh_status()

    def register_codex(self) -> None:
        if self._codex_task_in_progress:
            self.set_message('Codex MCP registration is already running.')
            return

        self._codex_task_in_progress = True
        self.set_message('Registering Codex MCP...')
        thread = threading.Thread(
            target=self._register_codex_worker,
            name='bridge-panel-register',
            daemon=True,
        )
        thread.start()

    def copy_codex_setup(self) -> None:
        payload = self.build_codex_setup_text()
        self.root.clipboard_clear()
        self.root.clipboard_append(payload)
        self.root.update()
        self.set_message('Codex setup copied to clipboard.')

    def on_close(self) -> None:
        stop_managed_bridge = False
        if self.managed_bridge_running():
            answer = messagebox.askokcancel(
                'Close Bridge Panel',
                'Closing this panel will also stop the bridge process started here. Continue?',
            )
            if not answer:
                return
            stop_managed_bridge = True

        self._closing = True
        self._cancel_refresh_job()
        self._cancel_ui_pump_job()

        if stop_managed_bridge:
            self.stop_bridge()
        self._close_bridge_logs()
        self.root.destroy()


def main() -> None:
    config_path = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else DEFAULT_CONFIG_PATH
    if not config_path.exists():
        raise SystemExit(f'Config file not found: {config_path}')

    root = tk.Tk()
    style = ttk.Style(root)
    if 'vista' in style.theme_names():
        style.theme_use('vista')

    BridgePanelApp(root, config_path)
    root.mainloop()


if __name__ == '__main__':
    main()
