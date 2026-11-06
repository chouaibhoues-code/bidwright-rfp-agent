"""One model call of one node, outside a run (Iteration 3, step 16; design section 4.11).

`call_node(node, task, schema, *, profile, mode, name)` builds a runtime in
`outputs/single/<name>/`, with its own `ledger.jsonl` and no run manifest, renders the node's
prompt with the task's JSON as its data, and makes the one call through
`RunContext.structured`, with its one format repair. `bidwright-eval techcheck` and
`bidwright-eval cards` (step 18) use it: each judges one item at a time, so a whole run would
measure much else beside the call.

The call keeps every rule of a run's call: the profile's model for the node's role, the
cassette key with its repeat index, the ledger's cost and shadow cost, and the run budget of
the profile's `dev` tier.
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from bidwright.config import Config, load_config
from bidwright.graph.build import run_prompts
from bidwright.graph.nodes import RunContext
from bidwright.harness.budget import RunBudget
from bidwright.llm.client import Backend, LLMClient, Mode
from bidwright.llm.replay import CassetteStore
from bidwright.obs.ledger import LedgerFile
from bidwright.preflight import HOME, Refused

SINGLE = "single"
LEDGER = "ledger.jsonl"


@dataclass(frozen=True)
class SingleCall:
    """What one call returned: the parsed answer, or None when it broke its schema twice."""

    parsed: BaseModel | None
    folder: Path


def single_folder(name: str, outputs: Path | None = None) -> Path:
    return (outputs or HOME / "outputs") / SINGLE / name


def single_context(
    name: str,
    *,
    profile: str,
    mode: Mode,
    backends: dict[str, Backend] | None = None,
    cassettes: CassetteStore | None = None,
    repeat: int = 0,
    outputs: Path | None = None,
    config: Config | None = None,
) -> RunContext:
    """A `RunContext` whose calls go to `outputs/single/<name>/ledger.jsonl`, for a node's own
    code to call as it would in a run."""
    config = config or load_config()
    if mode != "replay" and not backends:
        raise Refused(f"a {mode} call needs a backend for the profile {profile!r}")
    folder = single_folder(name, outputs)
    folder.mkdir(parents=True, exist_ok=True)
    ledger_file = LedgerFile(folder / LEDGER)
    if not (folder / LEDGER).exists():
        ledger_file.create()
    client = LLMClient(config, profile, backends or {}, mode=mode, cassettes=cassettes, run_id=name)
    budget = RunBudget(config.limits.run("dev", profile))
    budget.start()
    return RunContext(
        name, client, budget, run_prompts(config), {}, repeat=repeat, ledger_file=ledger_file
    )


def call_node(
    node: str,
    task: BaseModel,
    schema: type[BaseModel],
    *,
    profile: str,
    mode: Mode,
    name: str,
    backends: dict[str, Backend] | None = None,
    cassettes: CassetteStore | None = None,
    repeat: int = 0,
    outputs: Path | None = None,
    config: Config | None = None,
) -> SingleCall:
    """One call of `node`'s prompt on `task`, recorded in `outputs/single/<name>/ledger.jsonl`."""
    ctx = single_context(
        name,
        profile=profile,
        mode=mode,
        backends=backends,
        cassettes=cassettes,
        repeat=repeat,
        outputs=outputs,
        config=config,
    )
    if node not in ctx.prompts:
        raise Refused(f"no prompt for node {node!r}; a run loads {', '.join(sorted(ctx.prompts))}")
    folder = single_folder(name, outputs)
    prompt = ctx.prompts[node]
    data = task.model_dump_json()
    rendered = prompt.render(data, run_id=name)
    parsed, _ = ctx.structured(
        prompt, list(rendered.messages), schema, node=node, input_hash=rendered.input_hash
    )
    return SingleCall(parsed if isinstance(parsed, schema) else None, folder)


def read_calls(folder: Path) -> list[dict[str, Any]]:
    """The ledger entries a single-call folder holds."""
    from bidwright.obs.ledger import read_ledger

    return [entry.model_dump(mode="json") for entry in read_ledger(folder / LEDGER)]


__all__ = ["SINGLE", "SingleCall", "call_node", "read_calls", "single_folder"]
