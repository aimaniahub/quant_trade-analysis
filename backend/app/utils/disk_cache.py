"""
Disk cache helper for persisting state (jobs, radar board, symbol store)
when Redis is unavailable. Works across restarts and serverless container lifecycles.
"""
from __future__ import annotations

import json
import logging
import os
import tempfile
from typing import Any, Optional

logger = logging.getLogger(__name__)


def get_data_dir() -> str:
    """Return an absolute path to the data directory, creating it if needed."""
    base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "data"))
    try:
        os.makedirs(base_dir, exist_ok=True)
        test_file = os.path.join(base_dir, ".write_test")
        with open(test_file, "w", encoding="utf-8") as f:
            f.write("ok")
        try:
            os.remove(test_file)
        except Exception:
            pass
        return base_dir
    except Exception:
        tmp = os.path.join(tempfile.gettempdir(), "optiongreek_data")
        try:
            os.makedirs(tmp, exist_ok=True)
            return tmp
        except Exception:
            return tempfile.gettempdir()


def save_json_file(filename: str, data: Any) -> bool:
    """Atomically write data as JSON to filename in the data directory."""
    try:
        directory = get_data_dir()
        path = os.path.join(directory, filename)
        tmp_path = f"{path}.tmp"
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(data, f, default=str)
        if os.path.exists(path):
            os.replace(tmp_path, path)
        else:
            os.rename(tmp_path, path)
        return True
    except Exception as exc:
        logger.debug("[disk_cache] save %s failed: %s", filename, exc)
        return False


def load_json_file(filename: str) -> Optional[Any]:
    """Load JSON data from filename in the data directory, or return None."""
    try:
        directory = get_data_dir()
        path = os.path.join(directory, filename)
        if not os.path.exists(path):
            return None
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as exc:
        logger.debug("[disk_cache] load %s failed: %s", filename, exc)
        return None
