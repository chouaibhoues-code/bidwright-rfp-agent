"""Replays of the live recordings in `tests/cassettes/<name>/`, as `bidwright demo` replays
the demo: on the profile, input and stop that `recording.json` names, with Docling replayed
too, so no replay needs keys, a model or the Docling service. A recording whose pack size or
second-pass setting differs from `config/limits.yaml` fails first, with a message that says
which one, since neither is part of a cassette key. A replay runs in the recording's own
research mode, `off` for a recording made before Iteration 2, unless `research` names another."""

import json
from pathlib import Path
from typing import Any

from bidwright.cli import replay_arguments, stale_recording
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
    stale = stale_recording(recording, load_config().limits)
    assert stale is None, f"tests/cassettes/{name}: {stale}"
    arguments = replay_arguments(recording)
    if research is not None:
        arguments["research"] = research
    result = execute(
        **arguments,
        docling_mode="replay",
        outputs=outputs,
        cassettes=CassetteStore(store),
        run_id=f"replay-{name}",
    )
    return result, recording
