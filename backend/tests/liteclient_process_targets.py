"""Minimal spawn targets for liteclient supervisor process-boundary tests."""

from __future__ import annotations

import os
from pathlib import Path
import signal
import time


def ignore_sigterm(input_path: str, output_path: str) -> None:
    del input_path, output_path
    signal.signal(signal.SIGTERM, signal.SIG_IGN)
    pid_path = os.environ.get("GRAM_SCOPE_TEST_CHILD_PID_PATH")
    if pid_path:
        Path(pid_path).write_text(str(os.getpid()), encoding="ascii")
    while True:
        time.sleep(1)
