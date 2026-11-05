"""Whole-file writes (Iteration 2, ADR-031).

`write_atomic` writes the text to a staging file in the target's folder and moves it into place
with `os.replace`, so a reader, or a run resumed after a kill, finds either the old file or the
new one, never half of one. The staging file is named `<name>.<random>.tmp`, which no reader
looks for and no store lists, so one that a kill leaves behind is ignored; a write that fails
removes its own. The cassette stores (`llm/replay.py`) and the limiter's quota counts
(`llm/limits.py`) write through it.
"""

import os
import uuid
from pathlib import Path


def write_atomic(path: Path, text: str) -> None:
    """Write `text` to `path` whole, in UTF-8 with LF line endings."""
    path.parent.mkdir(parents=True, exist_ok=True)
    staged = path.with_name(f"{path.name}.{uuid.uuid4().hex[:12]}.tmp")
    try:
        with staged.open("x", encoding="utf-8", newline="\n") as stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(staged, path)
    except BaseException:
        staged.unlink(missing_ok=True)
        raise


__all__ = ["write_atomic"]
