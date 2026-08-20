from __future__ import annotations

import argparse
import os
import subprocess
from pathlib import Path


CREATE_BREAKAWAY_FROM_JOB = 0x01000000


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Start the Bridge outside the launcher's Windows job")
    parser.add_argument("--python", required=True)
    parser.add_argument("--wrapper", required=True)
    parser.add_argument("--workdir", required=True)
    return parser.parse_args()


def main() -> None:
    if os.name != "nt":
        raise SystemExit("Detached Bridge spawning is supported only on Windows")

    args = parse_args()
    python_executable = Path(args.python).resolve()
    wrapper = Path(args.wrapper).resolve()
    workdir = Path(args.workdir).resolve()
    for path, label in (
        (python_executable, "Python executable"),
        (wrapper, "Bridge process wrapper"),
        (workdir, "Bridge working directory"),
    ):
        if not path.exists():
            raise SystemExit(f"{label} does not exist: {path}")

    creationflags = (
        subprocess.CREATE_NEW_PROCESS_GROUP
        | subprocess.DETACHED_PROCESS
        | CREATE_BREAKAWAY_FROM_JOB
    )
    process = subprocess.Popen(
        [str(python_executable), str(wrapper)],
        cwd=str(workdir),
        env=os.environ.copy(),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        close_fds=True,
        creationflags=creationflags,
    )
    print(process.pid, flush=True)


if __name__ == "__main__":
    main()
