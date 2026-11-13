"""The code fixes of the drift report of 2026-11-12, before the `v0.3` tag."""

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from bidwright import cli
from bidwright.config import load_config
from bidwright.graph import solution
from bidwright.graph.blueprint import revise
from bidwright.graph.build import execute
from bidwright.graph.solution import _excerpt_views, degraded_reasons
from bidwright.llm.replay import CassetteStore
from bidwright.research.pack import load_pack
from bidwright.schemas import ResearchRecord
from tests.node_fakes import DEV_RFP, ScriptBackend, context, text
from tests.test_blueprint import SRC, TASK, plan, run
from tests.test_decide import FIXTURE_PACK, PATTERNS

CONFIG = load_config()


class Events:
    def __init__(self) -> None:
        self.rows: list[tuple[str, str | None, str]] = []

    def record(self, kind: str, node: str | None, detail: str) -> None:
        self.rows.append((kind, node, detail))


def _rt(tmp_path: Path, record: ResearchRecord | None, mode: str = "pack") -> Any:
    if record is not None:
        (tmp_path / "research.json").write_text(record.model_dump_json(), encoding="utf-8")
    research = CONFIG.research.model_copy(update={"packs_dir": str(FIXTURE_PACK.parent)})
    return SimpleNamespace(
        config=CONFIG.model_copy(update={"research": research}),
        research_mode=mode,
        run_dir=tmp_path,
        events=Events(),
    )


def test_a_failed_revision_counts_as_revised_so_techcheck_does_not_send_it_back() -> None:
    """A1: a failed P03 kept revision 0 at revision 0, so `techcheck` found the same claim
    INVALIDATED and sent the manifest back again, until the budget stopped the run."""
    first, _ = run([plan(), {"workstreams": []}])
    previous = first.manifest
    backend = ScriptBackend([text("not json"), text("not json")])
    assert first.plan is not None
    kept = revise(context(backend), first.plan, [], previous, TASK.claims, SRC)
    assert kept.failure is None and kept.manifest.revision == 1
    assert kept.manifest.work_packages == previous.work_packages
    assert any("counted as revised" in n for n in kept.manifest.notes)


def test_domain_needs_get_the_loaded_packs_excerpts(tmp_path: Path) -> None:
    """B1: `decide_plan` passed no excerpts, so every DOMAIN need reached `decide` without
    the evidence its prompt and context manifest named."""
    pack = load_pack(FIXTURE_PACK, PATTERNS)
    record = ResearchRecord(mode="pack", pack_id="fixture", pack_sha256=pack.sha256)
    views = _excerpt_views(_rt(tmp_path, record))
    clean = [e for e in pack.excerpts if not e.quarantined]
    assert views and set(views) == {e.id for e in clean}
    first = next(iter(views.values()))
    assert first.source_title and 1 <= first.tier <= 4 and first.text


def test_a_changed_pack_gives_no_excerpts_and_leaves_an_event(tmp_path: Path) -> None:
    """A8: the note that `ask_research` is withheld was discarded."""
    record = ResearchRecord(mode="pack", pack_id="fixture", pack_sha256="sha256:" + "0" * 64)
    rt = _rt(tmp_path, record)
    assert _excerpt_views(rt) == {}
    assert [(k, n) for k, n, _ in rt.events.rows] == [("research", "decide")]
    assert _excerpt_views(_rt(tmp_path, None, mode="off")) == {}


def test_a_same_family_reason_is_given_once_and_techcheck_can_give_it() -> None:
    """A5: `techcheck`'s verdict calls on route `same` now degrade the run too; one reason."""
    reason = "assess: SAME_FAMILY"
    both = {"assess_degraded": reason, "techcheck": {"degraded": reason}}
    assert degraded_reasons(both) == [reason]
    assert degraded_reasons({"techcheck": {"degraded": reason}}) == [reason]
    assert degraded_reasons({"techcheck": {"revision_due": False}}) == []


def test_context7_gets_the_runs_breaker(monkeypatch: pytest.MonkeyPatch) -> None:
    """A3: Context7's client had no breaker in a run, so an open breaker never stopped it."""
    seen: list[Any] = []

    class Docs:
        def gateway(self, *_: Any) -> object:
            return object()

    def fake(config: Any, patterns: Any, events: Any = None, breaker: Any = None) -> Docs:
        seen.append(breaker)
        return Docs()

    monkeypatch.setattr(solution, "context7_docs", fake)
    monkeypatch.setattr(solution, "RuleContext", lambda **_: object())
    breaker = object()
    rt = SimpleNamespace(
        config=CONFIG,
        research_mode="live",
        events=None,
        breaker=breaker,
        tool_log=None,
        ctx=SimpleNamespace(passages={}, view=None),
    )
    solution._tech_sources(rt)
    assert seen == [breaker]


def test_a_run_with_reflect_on_checks_its_server_against_the_register(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A4: the egress check never saw the stdio server behind `reflect`."""
    seen: list[list[str]] = []

    def stop(*_: Any, research: Any = (), **__: Any) -> list[str]:
        seen.append([name for name, _ in research])
        raise RuntimeError("checked")

    monkeypatch.setattr("bidwright.graph.build.check_run", stop)
    for reflect in (True, False):
        with pytest.raises(RuntimeError, match="checked"):
            execute(
                source=DEV_RFP,
                profile="free",
                outputs=tmp_path,
                mode="replay",
                docling_mode="replay",
                cassettes=CassetteStore(tmp_path / "empty"),
                reflect=reflect,
            )
    assert seen == [["reflect"], []]


@pytest.mark.parametrize(
    ("address", "env", "refused"),
    [
        ("127.0.0.1", None, False),
        ("localhost", None, False),
        ("0.0.0.0", None, True),  # noqa: S104
        ("0.0.0.0", "container", False),  # noqa: S104
        ("192.168.1.20", None, True),
    ],
)
def test_the_ui_and_the_api_bind_loopback_on_the_host(
    monkeypatch: pytest.MonkeyPatch, address: str, env: str | None, refused: bool
) -> None:
    """A7: the UI has no Host check, so on the host it listens on loopback only."""
    if env is None:
        monkeypatch.delenv("BIDWRIGHT_ENV", raising=False)
    else:
        monkeypatch.setenv("BIDWRIGHT_ENV", env)
    assert (cli._loopback_only(address) is not None) is refused
