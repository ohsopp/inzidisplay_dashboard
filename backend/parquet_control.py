"""
Runtime control for parquet write enable/disable.
Default: enabled, unless PARQUET_WRITE_ENABLED is explicitly false-like.
"""
from __future__ import annotations

import os
import threading

_LOCK = threading.Lock()
_STATE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".parquet_write_enabled")


def _env_enabled_default() -> bool:
    raw = (os.environ.get("PARQUET_WRITE_ENABLED") or "").strip().lower()
    if not raw:
        return True
    return raw in ("1", "true", "yes", "on")


_ENABLED = _env_enabled_default()


def _read_state_file() -> bool | None:
    try:
        with open(_STATE_FILE, "r", encoding="utf-8") as rf:
            raw = rf.read().strip().lower()
    except OSError:
        return None
    if raw in ("1", "true", "yes", "on"):
        return True
    if raw in ("0", "false", "no", "off"):
        return False
    return None


def _write_state_file(enabled: bool) -> None:
    try:
        with open(_STATE_FILE, "w", encoding="utf-8") as wf:
            wf.write("1" if enabled else "0")
    except OSError:
        pass


def is_parquet_write_enabled() -> bool:
    with _LOCK:
        file_state = _read_state_file()
        if file_state is not None:
            return file_state
        return bool(_ENABLED)


def set_parquet_write_enabled(enabled: bool) -> bool:
    global _ENABLED
    with _LOCK:
        _ENABLED = bool(enabled)
        _write_state_file(_ENABLED)
        return _ENABLED


# initialize state file once so subprocesses/modules share same toggle state
_write_state_file(_ENABLED)
