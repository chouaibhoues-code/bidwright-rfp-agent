"""Replays of the live recordings in `tests/cassettes/<name>/`, as `bidwright demo` replays
the demo: on the profile, input and stop that `recording.json` names, with Docling replayed
too, so no replay needs keys, a model or the Docling service."""

import json
from pathlib import Path
from typing import Any

from bidwright.graph.build import RunResult, execute
from bidwright.llm.replay import CassetteStore
from bidwright.preflight import HOME

CASSETTES = HOME / "tests" / "cassettes"


def replay(name: str, outputs: Path) -> tuple[RunResult, dict[str, Any]]:
    store = CASSETTES / name
    recording = json.loads((store / "recording.json").read_text(encoding="utf-8"))
    result = execute(
        docling_mode="replay",
        source=HOME / recording["source"],
        profile=recording["profile"],
        outputs=outputs,
        mode="replay",
        cassettes=CassetteStore(store),
        until=recording.get("until", "render"),
        run_id=f"replay-{name}",
    )
    return result, recording
