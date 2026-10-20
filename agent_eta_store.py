"""The state files of agent-eta: JSON objects written atomically into the state directory."""

import json
import os
import re


def read_json(path):
    """A JSON object from path, or None when it is missing or not an object."""
    try:
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def safe_id(text):
    return re.sub(r"[^A-Za-z0-9_.-]", "_", str(text))[:120]


def write_atomic(path, data):
    """Write JSON through a temporary file in the same directory, then rename.

    The reader may look at any moment, and a half-written entry would read as garbage.
    """
    tmp = "%s.tmp.%d" % (path, os.getpid())
    try:
        with open(tmp, "w", encoding="utf-8") as handle:
            json.dump(data, handle, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
    except OSError:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def sub_dir(directory, name):
    """sessions/, turns/ or cache/ in the state directory, created on first write."""
    path = os.path.join(directory, name)
    try:
        os.mkdir(path, 0o700)
    except FileExistsError:
        pass
    return path
