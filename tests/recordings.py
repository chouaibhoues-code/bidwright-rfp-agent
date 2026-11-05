"""Replays of the live recordings in `tests/cassettes/<name>/`, as `bidwright demo` replays
the demo: on the profile, input and stop that `recording.json` names, with Docling replayed
too, so no replay needs keys, a model or the Docling service. A recording whose pack size or
second-pass setting differs from `config/limits.yaml` fails first, with a message that says
which one, since neither is part of a cassette key. A replay runs in the recording's own
research mode, `off` for a recording made before Iteration 2, unless `research` names another."""

import json
from pathlib import Path
from typing import Any

from bidwright.cli import stale_recording
from bidwright.config import load_config
from bidwright.graph.build import RunResult, execute
from bidwright.llm.replay import CassetteStore
from bidwright.preflight import HOME
from bidwright.schemas import ResearchModeName

CASSETTES = HOME / "tests" / "cassettes"


def replay(
    name: str, outputs: Path, research: ResearchModeName | None = None
) -> tuple[RunResult, dict[str, Any]]:
    store = CASSETTES / name
    recording = json.loads((store / "recording.json").read_text(encoding="utf-8"))
    limits = load_config().limits
    stale = stale_recording(recording, limits.batch_size, limits.second_pass)
    assert stale is None, f"tests/cassettes/{name}: {stale}"
    result = execute(
        docling_mode="replay",
        source=HOME / recording["source"],
        profile=recording["profile"],
        outputs=outputs,
        mode="replay",
        cassettes=CassetteStore(store),
        until=recording.get("until", "render"),
        research=research or recording.get("research", "off"),
        run_id=f"replay-{name}",
        assess_route=recording.get("assess_route"),
    )
    return result, recording
