"""Whole-file writes and the run's line files (Iteration 2, ADR-031).

`write_atomic` writes the text to a staging file in the target's folder and moves it into place
with `os.replace`, so a reader, or a run resumed after a kill, finds either the old file or the
new one, never half of one. The staging file is named `<name>.<random>.tmp`, which no reader
looks for and no store lists, so one that a kill leaves behind is ignored; a write that fails
removes its own. The cassette stores (`llm/replay.py`) and the limiter's quota counts
(`llm/limits.py`) write through it.

A run's line files, `ledger.jsonl`, `events.jsonl`, `tool_calls.jsonl` and `dead_letter.jsonl`,
grow one line per record. A kill can leave a last line without its newline: `read_lines`
skips it, and `repair_lines`, which a resume runs on each file before it appends, cuts it, so
a new line never lands on the end of a cut one.
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


def complete_lines(data: bytes) -> int:
    """How many bytes of `data` end at a newline: everything after the last one is a line
    that was never finished."""
    return data.rfind(b"\n") + 1


def read_lines(path: Path) -> list[str]:
    """The finished, non-blank lines of a line file; none when it does not exist."""
    if not path.exists():
        return []
    data = path.read_bytes()
    whole = data[: complete_lines(data)].decode("utf-8")
    return [line for line in whole.splitlines() if line.strip()]


def repair_lines(path: Path) -> str:
    """Cut a last line that a kill left without its newline, and return the text cut; "" when
    there is none, or no file."""
    if not path.exists():
        return ""
    data = path.read_bytes()
    end = complete_lines(data)
    if end == len(data):
        return ""
    with path.open("r+b") as stream:
        stream.truncate(end)
    return data[end:].decode("utf-8", errors="replace")


__all__ = ["complete_lines", "read_lines", "repair_lines", "write_atomic"]
