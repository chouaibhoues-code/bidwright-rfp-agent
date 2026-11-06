"""A run for `tests/test_resume.py` to kill:

    python -m tests.kill_target <outputs> <state> <script> <marker>

It runs the development PDF live, with Docling replayed and one `Send` worker at a time, under
`ScriptedRun`. When the backend reaches its scripted blocking call, it writes `<marker>` and
waits for good, and the test kills the process there, as an operator's kill would. `<state>`
holds the quota, breaker and cache folders, which the fixtures of `tests/conftest.py` do not
reach in a subprocess.
"""

import json
import sys
import threading
from pathlib import Path

import bidwright.harness.recovery
import bidwright.llm.cache
import bidwright.llm.limits
from bidwright.config import Config, load_config
from bidwright.llm.types import Request, Response
from tests.node_fakes import DEV_RFP, USAGE, RuleBackend, data_of, fake_backends

RUN_ID = "killed"
SCRIPTS = ("extract", "consolidate")
SECOND_READING = "first reading missed"  # words only the extract prompt's second-pass task holds


def one_worker() -> Config:
    """The configuration with one `Send` worker at a time, so a fan-out runs in a fixed order."""
    config = load_config()
    concurrency = {**config.limits.concurrency, "free": 1}
    limits = config.limits.model_copy(update={"concurrency": concurrency})
    return config.model_copy(update={"limits": limits})


def kind(request: Request) -> str:
    """Which scripted call a request is: `B01` and `B01-repair` for the first pack's first
    reading and its repair, `RG-002` for a cluster's call, or the schema's name."""
    data = data_of(request)
    answered = any(m.role == "assistant" for m in request.messages)
    if request.schema_name == "ExtractResult" and data.get("batch_id") == "B01":
        user = " ".join(m.content for m in request.messages if m.role == "user")
        if SECOND_READING in user:
            return "B01-second"
        return "B01-repair" if answered else "B01"
    if request.schema_name == "ConsolidationResult":
        return str(data.get("cluster_id", ""))
    return request.schema_name or "tools"


class ScriptedRun(RuleBackend):
    """`RuleBackend` with the faults a resume test scripts.

    - `extract`: B01's first reading omits a required id, so a repair follows, and the repair
      blocks.
    - `consolidate`: RG-002 answers malformed twice, so it falls back to code, and RG-003
      blocks.

    With `block=False` the same answers come back without blocking: the uninterrupted run, and
    the resumed one. Every request is kept, with its kind."""

    def __init__(self, script: str, *, block: bool = True, marker: Path | None = None) -> None:
        if script not in SCRIPTS:
            raise ValueError(f"unknown script {script!r}")
        super().__init__()
        self.script = script
        self.block = block
        self.marker = marker
        self.kinds: list[str] = []
        self.release = threading.Event()
        self._lock = threading.Lock()

    def call(self, request: Request) -> Response:
        name = kind(request)
        with self._lock:
            self.kinds.append(name)
        if self.block and name == ("B01-repair" if self.script == "extract" else "RG-003"):
            if self.marker is not None:
                self.marker.write_text(name, encoding="utf-8")
            self.release.wait()
        if self.script == "consolidate" and name == "RG-002":
            self.requests.append(request)
            return Response(text="{not json", usage=USAGE)
        response = super().call(request)
        if self.script == "extract" and name == "B01":
            return _omit_one(response)
        return response


def _omit_one(response: Response) -> Response:
    """The answer without one passage it was asked to account for."""
    body = json.loads(response.text)
    if body["no_obligation_src_ids"]:
        body["no_obligation_src_ids"] = body["no_obligation_src_ids"][:-1]
    else:
        body["items"] = body["items"][:-1]
    return Response(text=json.dumps(body), usage=response.usage)


def main(argv: list[str]) -> int:
    outputs, state, script, marker = Path(argv[0]), Path(argv[1]), argv[2], Path(argv[3])
    bidwright.llm.limits.QUOTA_DIR = state / ".quota"
    bidwright.harness.recovery.BREAKER_DIR = state / ".quota" / "breaker"
    bidwright.llm.cache.CACHE_DIR = state / ".cache"
    from bidwright.graph.build import execute

    execute(
        source=DEV_RFP,
        profile="free",
        outputs=outputs,
        docling_mode="replay",
        backends=fake_backends(ScriptedRun(script, marker=marker)),
        run_id=RUN_ID,
        config=one_worker(),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
