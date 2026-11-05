"""The events log (Iteration 2, ADR-031): `events.jsonl`, one `EventRecord` per line.

`EventRecorder` is the file's only writer. It appends under a lock, since the `Send` workers
record events in parallel, and each row carries `part`, the run's resume count, so a row written
again after a resume is told apart from the first and nothing is ever deleted. Kinds are
`status` (every transition the supervisor records), `gateway`, `recovery`, `research` and
`security`; only a security event carries an attribution class.
"""

import threading
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

from bidwright.schemas import Attribution, EventKind, EventRecord


def utc_now() -> datetime:
    """The current time in UTC, to the second, as the run's files record it."""
    return datetime.now(UTC).replace(microsecond=0)


class EventRecorder:
    def __init__(self, path: Path, part: int = 0, clock: Callable[[], datetime] = utc_now) -> None:
        self.path = path
        self.part = part
        self._clock = clock
        self._lock = threading.Lock()

    def create(self) -> None:
        """An empty log, written when a fresh run starts in its folder."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text("", encoding="utf-8", newline="\n")

    def record(
        self,
        kind: EventKind,
        node: str | None,
        detail: str,
        attribution: Attribution | None = None,
    ) -> EventRecord:
        event = EventRecord(
            at=self._clock(),
            part=self.part,
            kind=kind,
            node=node,
            detail=detail,
            attribution=attribution,
        )
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8", newline="\n") as stream:
                stream.write(event.model_dump_json() + "\n")
        return event


def read_events(path: Path) -> list[EventRecord]:
    """The log's rows; a last line that a kill cut short is skipped, as in the ledger."""
    if not path.exists():
        return []
    data = path.read_bytes()
    whole = data[: data.rfind(b"\n") + 1].decode("utf-8")
    return [EventRecord.model_validate_json(line) for line in whole.splitlines() if line.strip()]


__all__ = ["EventRecorder", "read_events", "utc_now"]
