"""The `assess` role's route (ADR-045): set once a run from the backends present, taken from
the recording on a replay and from the first part on a resume, `same` on a client run, and
handed to the client in place of the configured role."""

from pathlib import Path

import pytest

from bidwright.config import load_config
from bidwright.graph import build
from bidwright.graph.build import execute
from bidwright.llm.client import LLMClient, choose_route, route_config
from bidwright.llm.openai_compat import OpenAICompatBackend
from bidwright.llm.types import Message
from bidwright.preflight import Refused
from bidwright.schemas import ExtractResult, LedgerEntry, RunManifest
from tests.llm_fakes import CALL, FakeBackend
from tests.node_fakes import DEV_RFP, RuleBackend

CONFIG = load_config()
CEREBRAS = OpenAICompatBackend("cerebras", "https://api.cerebras.ai/v1", "unused")
GROQ = OpenAICompatBackend("groq", "https://api.groq.com/openai/v1", "unused")


def _route(backends: dict[str, object], **kwargs: object) -> str | None:
    options: dict[str, object] = {
        "given": None,
        "mode": "live",
        "client": False,
        "resume": False,
        "llm": True,
    }
    options.update(kwargs)
    return build._assess_route(CONFIG, "free", backends, **options)  # type: ignore[arg-type]


def test_a_live_run_takes_the_first_route_whose_provider_has_a_backend() -> None:
    gemini = FakeBackend()
    assert _route({"gemini": gemini, "cerebras": CEREBRAS, "groq": GROQ}) == "primary"
    assert _route({"gemini": gemini, "groq": GROQ}) == "fallback"
    assert _route({"gemini": gemini}) == "same"


def test_a_replay_takes_its_recordings_route_and_primary_when_it_names_none() -> None:
    assert _route({}, mode="replay") == "primary"
    assert _route({}, mode="replay", given="fallback") == "fallback"


def test_a_client_run_takes_route_same() -> None:
    assert _route({"gemini": FakeBackend(), "cerebras": CEREBRAS}, client=True) == "same"


def test_a_resume_keeps_its_route_and_is_refused_without_that_backend() -> None:
    assert _route({"gemini": FakeBackend(), "cerebras": CEREBRAS}, given="fallback") == "fallback"
    with pytest.raises(Refused, match="route fallback, served by groq"):
        _route({"gemini": FakeBackend(), "cerebras": CEREBRAS}, given="fallback", resume=True)
    with pytest.raises(Refused, match="assess_route takes one of"):
        _route({}, given="sideways")


def test_a_profile_without_a_routed_assess_has_no_route() -> None:
    config = CONFIG.model_copy(deep=True)
    for roles in config.models.profiles.values():
        roles.pop("assess")
    assert (
        build._assess_route(
            config, "free", {}, given=None, mode="live", client=False, resume=False, llm=True
        )
        is None
    )


def test_each_route_serves_its_own_model() -> None:
    assess = CONFIG.models.role("free", "assess")
    assert route_config(CONFIG, "free", "assess", "primary") == assess
    fallback = route_config(CONFIG, "free", "assess", "fallback")
    assert (fallback.provider, fallback.model, fallback.fallback) == (
        "groq",
        "openai/gpt-oss-120b",
        None,
    )
    assert route_config(CONFIG, "free", "assess", "same") == CONFIG.models.role("free", "reason")
    assert choose_route(assess, {}) == "same"


def test_role_overrides_replace_the_configured_role_and_shadow_roles_price_it() -> None:
    backend = FakeBackend(provider="gemini")
    entries: list[LedgerEntry] = []
    client = LLMClient(
        CONFIG,
        "free",
        {"gemini": backend},
        role_overrides={"assess": route_config(CONFIG, "free", "assess", "same")},
        shadow_roles={"assess": "reason"},
        on_ledger=entries.append,
    )
    client.complete("assess", [Message("user", "x")], ExtractResult, **CALL)
    assert backend.models == [CONFIG.models.role("free", "reason").model]
    # 1,000 tokens in and 200 out at gemini-3.5-flash-lite's list price, the reason role's
    # shadow model, not at gpt-oss-120b's, the assess role's.
    assert entries[0].shadow_cost_usd == pytest.approx(1000 * 0.30e-6 + 200 * 2.50e-6)
    assert entries[0].cost_usd == 0.0


def test_a_run_records_its_route_in_the_manifest_and_names_the_routes_model(
    tmp_path: Path,
) -> None:
    result = execute(
        docling_mode="replay",
        source=DEV_RFP,
        profile="free",
        outputs=tmp_path / "out",
        backends={"gemini": RuleBackend()},
        until="verify",
        run_id="route-same",
    )
    assert result.assess_route == "same"
    manifest = RunManifest.model_validate_json(
        (result.run_dir / "run_manifest.json").read_text(encoding="utf-8")
    )
    assert manifest.run_args["assess_route"] == "same"
    assert manifest.models["assess"] == CONFIG.models.role("free", "reason").model
