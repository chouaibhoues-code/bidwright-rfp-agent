"""Recovery (Iteration 2): the circuit breaker and the dead-letter file.

`CircuitBreaker` counts consecutive failed attempts per key: a model on a provider and tier,
such as `gemini-free-gemini-3.5-flash-lite`, or an MCP server, such as `mcp-notebooklm`. A
failure is an attempt that fails with a transient error: a rate limit that `genai._translate`
does not classify as a spent daily quota (ADR-029), a timeout, a server error or a transport
error; for a server, a tool error or a failed connection. A spent quota, any other 4xx status
and an unparseable answer are not failures, and an attempt that gets an answer resets the
count. `failures` consecutive failures open the breaker for `cooldown_minutes`; it then closes
with its count reset. The client checks it before each attempt, so a breaker that opens during
a call's retries stops the next attempt, and an open one raises `CircuitOpen`.

The state lives in `outputs/.quota/breaker/`, one file per key, named as `Limiter.path` names a
quota count without the day. Each file is written through `fileio.write_atomic` under an
in-process lock, so the `Send` workers of one run share it, and it holds across runs. Keying
on the tier lets `--profile paid` resume past a breaker opened on `free`.

`DeadLetters` is the only writer of a run's `dead_letter.jsonl`: one row per call id, for an
`extract` context pack rejected after its repair and a `consolidate` cluster that fell back to
code, each naming its context manifest. A call run again after a resume adds nothing. Each
breaker change and each dead letter is also an event of kind `recovery`.
"""

import json
import threading
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from bidwright.config import BreakerConfig
from bidwright.fileio import read_lines, write_atomic
from bidwright.llm.limits import QUOTA_DIR, model_key
from bidwright.llm.types import CircuitOpen
from bidwright.schemas import DeadLetter

BREAKER_DIR = QUOTA_DIR / "breaker"
DEAD_LETTERS = "dead_letter.jsonl"


def server_key(server: str) -> str:
    return f"mcp-{server}"


@dataclass(frozen=True)
class _State:
    failures: int = 0
    open_until: datetime | None = None


class CircuitBreaker:
    def __init__(
        self,
        config: BreakerConfig,
        root: Path | None = None,
        *,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
        on_change: Callable[[str], object] | None = None,
    ) -> None:
        self.config = config
        self.root = root if root is not None else BREAKER_DIR
        self.on_change = on_change
        self._now = now
        self._lock = threading.Lock()

    def path(self, key: str) -> Path:
        return self.root / f"{key}.json".replace("/", "_").replace(":", "_")

    def check(self, key: str, name: str) -> None:
        """Raise `CircuitOpen` while the breaker on `key` is open; close it once its cooldown
        has passed."""
        with self._lock:
            state = self._read(key)
            if state.open_until is None:
                return
            if self._now() < state.open_until:
                raise CircuitOpen(name, state.open_until)
            self._write(key, _State())
        self._changed(f"breaker closed on {key}: its cooldown ended")

    def failure(self, key: str) -> None:
        with self._lock:
            state = self._read(key)
            failures = state.failures + 1
            opened = state.open_until is None and failures >= self.config.failures
            until = (
                self._now() + timedelta(minutes=self.config.cooldown_minutes)
                if opened
                else state.open_until
            )
            self._write(key, _State(failures, until))
        if opened and until is not None:
            self._changed(
                f"breaker opened on {key} after {failures} consecutive failures, until"
                f" {until:%Y-%m-%dT%H:%M:%SZ}"
            )

    def success(self, key: str) -> None:
        with self._lock:
            state = self._read(key)
            if state == _State():
                return
            self._write(key, _State())

    def state(self, key: str) -> tuple[int, datetime | None]:
        """The consecutive failures counted on `key`, and when it reopens, if it is open."""
        with self._lock:
            state = self._read(key)
        return state.failures, state.open_until

    def _read(self, key: str) -> _State:
        path = self.path(key)
        if not path.exists():
            return _State()
        try:
            body = json.loads(path.read_text(encoding="utf-8"))
            until = body.get("open_until")
            return _State(int(body["failures"]), datetime.fromisoformat(until) if until else None)
        except (ValueError, KeyError, TypeError) as exc:
            raise ValueError(f"{path} is not a breaker state file: {exc}") from exc

    def _write(self, key: str, state: _State) -> None:
        until = state.open_until.isoformat() if state.open_until else None
        body = {"key": key, "failures": state.failures, "open_until": until}
        write_atomic(self.path(key), json.dumps(body) + "\n")

    def _changed(self, detail: str) -> None:
        if self.on_change is not None:
            self.on_change(detail)


class DeadLetters:
    """A run's `dead_letter.jsonl`, appended once per call id."""

    def __init__(self, run_dir: Path, on_add: Callable[[DeadLetter], object] | None = None) -> None:
        self.path = run_dir / DEAD_LETTERS
        self.on_add = on_add
        self._lock = threading.Lock()
        self._letters = read_dead_letters(self.path)

    def add(
        self, node: str, call_id: str, reason: str, attempts: int, manifest: str | None
    ) -> DeadLetter | None:
        """Write one dead letter, or nothing if this call id already has one."""
        with self._lock:
            if any(letter.call_id == call_id for letter in self._letters):
                return None
            letter = DeadLetter(
                id=f"DL-{len(self._letters) + 1:03d}",
                node=node,
                call_id=call_id,
                reason=reason,
                attempts=attempts,
                manifest=manifest,
            )
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8", newline="\n") as stream:
                stream.write(letter.model_dump_json() + "\n")
            self._letters.append(letter)
        if self.on_add is not None:
            self.on_add(letter)
        return letter


def read_dead_letters(path: Path) -> list[DeadLetter]:
    """The file's rows; a last line that a kill cut short is skipped, as in the ledger."""
    return [DeadLetter.model_validate_json(line) for line in read_lines(path)]


__all__ = [
    "BREAKER_DIR",
    "DEAD_LETTERS",
    "CircuitBreaker",
    "DeadLetters",
    "model_key",
    "read_dead_letters",
    "server_key",
]
