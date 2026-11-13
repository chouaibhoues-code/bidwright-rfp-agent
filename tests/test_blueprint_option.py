"""Which option `blueprint` builds for (step 22's code review)."""

from bidwright.graph.gate import SWITCH_FAILED
from bidwright.graph.solution import blueprint_option, failed_switch
from bidwright.schemas import SolutionOption, SolutionOptions

OPTIONS = SolutionOptions(
    options=[
        SolutionOption(id="OPT-2", name="B", rank=2),
        SolutionOption(id="OPT-1", name="A", rank=1),
    ]
)


def _picked(state: dict[str, object]) -> str | None:
    option = blueprint_option(OPTIONS, state)
    return option.id if option is not None else None


def test_the_first_blueprint_builds_for_the_top_ranked_option() -> None:
    assert _picked({}) == "OPT-1"


def test_a_switch_at_the_gate_builds_for_the_option_it_names() -> None:
    assert _picked({"gate": {"option_id": "OPT-2"}, "manifest": {"option_id": "OPT-1"}}) == "OPT-2"


def test_a_revision_after_a_switch_keeps_the_option_the_manifest_was_built_for() -> None:
    """Blueprint clears the gate's state, so a revision after techcheck finds no option there;
    it must not fall back to the top-ranked option."""
    assert _picked({"gate": {}, "manifest": {"option_id": "OPT-2"}}) == "OPT-2"


def test_no_option_gives_none() -> None:
    assert blueprint_option(SolutionOptions(options=[]), {}) is None


def test_a_failed_blueprint_after_a_switch_ends_the_run_with_nothing_drafted() -> None:
    """The second architecture review (DE-01): after a person's switch, the `approach` fallback
    would draft from something no person approved."""
    reason = failed_switch({"gate": {"option_id": "OPT-2"}}, "blueprint: malformed twice")
    assert reason is not None and reason.startswith(f"{SWITCH_FAILED}: the blueprint for OPT-2")
    assert "nothing is drafted" in reason


def test_a_failed_first_blueprint_keeps_the_fallback() -> None:
    assert failed_switch({"gate": {}}, "blueprint: malformed twice") is None
    assert failed_switch({}, "blueprint: malformed twice") is None
    assert failed_switch({"gate": {"option_id": "OPT-2"}}, None) is None
