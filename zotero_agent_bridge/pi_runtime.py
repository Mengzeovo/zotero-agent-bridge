from __future__ import annotations

import os
import platform
import re
import shutil
import signal
import subprocess
from pathlib import Path

from .errors import BridgeError


def resolve_pi_executable(configured: str, override: list[str] | None = None) -> list[str]:
    if override:
        return list(override)
    resolved_name = shutil.which(configured)
    executable = Path(resolved_name or configured).expanduser()
    if not resolved_name and (not executable.is_absolute() or not executable.is_file()):
        raise BridgeError(503, "pi_executable_not_found", "Pi CLI was not found. Install Pi or configure an absolute executable path.", {"configured": configured, "searched_path": os.environ.get("PATH", "")})
    if platform.system() != "Windows" or executable.suffix.lower() not in {".cmd", ".bat"}:
        return [str(executable.resolve())]
    if executable.suffix.lower() != ".cmd" or not executable.is_file():
        raise BridgeError(503, "pi_executable_unsupported", "Windows Pi launcher must be a standard npm .cmd shim or a direct executable", {"executable": str(executable)})
    text = executable.read_text(encoding="utf-8", errors="replace")
    match = re.search(r'%dp0%[\\/](?P<target>[^"\r\n]+?\.js)"\s+%\*', text, flags=re.IGNORECASE)
    if not match:
        raise BridgeError(503, "pi_executable_unsupported", "Could not safely resolve the Node CLI target from the npm launcher", {"executable": str(executable)})
    shim_root = executable.parent.resolve()
    target = (shim_root / Path(match.group("target").replace("\\", os.sep))).resolve()
    try:
        target.relative_to(shim_root)
    except ValueError as exc:
        raise BridgeError(503, "pi_executable_unsupported", "Resolved Pi Node CLI target escapes the npm launcher directory", {"target": str(target)}) from exc
    if not target.is_file():
        raise BridgeError(503, "pi_executable_unsupported", "Resolved Pi Node CLI target does not exist", {"target": str(target)})
    sibling_node = executable.parent / "node.exe"
    node = sibling_node if sibling_node.is_file() else Path(shutil.which("node") or "")
    if not node or not node.is_file():
        raise BridgeError(503, "pi_executable_unsupported", "Node.js executable was not found")
    return [str(node.resolve()), str(target)]


def popen_process_group_kwargs() -> dict[str, object]:
    if platform.system() == "Windows":
        return {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW}
    return {"start_new_session": True}


def terminate_process_tree(process: subprocess.Popen[bytes]) -> None:
    if process.poll() is not None:
        return
    if platform.system() == "Windows":
        try:
            process.send_signal(signal.CTRL_BREAK_EVENT)
            process.wait(timeout=1.0)
            return
        except (OSError, ValueError, subprocess.TimeoutExpired):
            pass
        try:
            result = subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"], check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=5)
            if result.returncode == 0:
                process.wait(timeout=2.0)
                return
        except (OSError, subprocess.TimeoutExpired):
            pass
        if process.poll() is None:
            process.kill()
    else:
        try:
            os.killpg(process.pid, signal.SIGTERM)
            process.wait(timeout=1.0)
            return
        except (OSError, ProcessLookupError, subprocess.TimeoutExpired):
            pass
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except (OSError, ProcessLookupError):
            process.kill()
    try:
        process.wait(timeout=2.0)
    except subprocess.TimeoutExpired:
        process.kill()
