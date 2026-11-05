"""Config tests: every file loads, validates, and agrees with the others."""

import re
from datetime import date
from typing import get_args

import pytest
from pydantic import ValidationError

from bidwright import schemas
from bidwright.config import (
    CUE_KINDS,
    RESEARCH_MODES,
    ZONE_NAMES,
    AgentConfig,
    AgentLimits,
    Config,
    CuesConfig,
    HttpServer,
    LintConfig,
    ResearchConfig,
    TiersConfig,
    load_config,
)

KNOWN_TOOLS = {"search_rfp", "date_calc", "ask_research", "start_research"}


@pytest.fixture(scope="module")
def config() -> Config:
    return load_config()


def test_every_file_loads(config: Config) -> None:
    assert config.models.profiles
    assert config.limits.batch_size >= 1  # the value is S-03's to set, so it is read, not pinned
    assert config.agents.agents
    assert config.thresholds.block
    assert config.pricing.models
    assert config.ingest.parsers.pdf == "docling"
    assert set(config.cues.kinds) == set(CUE_KINDS)
    assert set(CUE_KINDS) | {"TABLE_ROW"} == set(get_args(schemas.CueKind))
    assert tuple(config.zones.zones) == ZONE_NAMES == get_args(schemas.Zone)
    assert config.zones.default in config.zones.zones
    assert config.lint.rules and config.lint.contract and config.lint.checks and config.lint.units
    assert config.egress.destinations
    assert config.research.mode in RESEARCH_MODES
    assert "notebooklm" in config.research.servers and "notebooklm" in config.pins.servers
    assert config.limits.breaker.failures >= 1


def test_every_agent_role_has_a_model_in_every_profile(config: Config) -> None:
    for name, agent in config.agents.agents.items():
        for profile in config.models.profiles:
            assert config.models.role(profile, agent.model_role), (name, profile)


def test_agent_io_names_are_real_schemas(config: Config) -> None:
    for agent in config.agents.agents.values():
        assert hasattr(schemas, agent.input), agent.input
        assert hasattr(schemas, agent.output), agent.output


def test_agent_tools_exist(config: Config) -> None:
    for agent in config.agents.agents.values():
        assert set(agent.tools) <= KNOWN_TOOLS


def test_only_the_agent_declares_limits(config: Config) -> None:
    """A function's one call and one repair are fixed in code, so nothing declares them."""
    for name, agent in config.agents.agents.items():
        declared = agent.limits.model_dump(exclude_unset=True)
        assert bool(declared) == (agent.kind == "agent"), name


@pytest.mark.parametrize(
    ("model", "field"),
    [
        (AgentLimits, "max_calls"),
        (AgentLimits, "max_repairs"),
        (AgentConfig, "cards"),
        (AgentConfig, "skills"),
    ],
)
def test_a_field_that_nothing_enforces_cannot_be_declared(model: type, field: str) -> None:
    base = {} if model is AgentLimits else _function()
    with pytest.raises(ValidationError):
        model.model_validate({**base, field: 1})


def _function() -> dict[str, object]:
    return {
        "kind": "function",
        "input": "ExtractBatch",
        "output": "ExtractResult",
        "prompt": "extract@0.2.0",
        "model_role": "extract",
    }


def test_free_models_and_shadow_models_have_prices(config: Config) -> None:
    today = date(2026, 11, 3)
    for role in config.models.profiles["free"].values():
        assert config.pricing.price(role.model, today) is not None, role.model
    for model in config.pricing.shadow_model.values():
        assert config.pricing.price(model, today) is not None, model


def test_flash_price_doubles_after_2026(config: Config) -> None:
    before = config.pricing.price("gemini-3.8-flash", date(2026, 12, 31))
    after = config.pricing.price("gemini-3.8-flash", date(2027, 1, 1))
    assert before is not None and after is not None
    assert after.input == 2 * before.input
    assert after.output == 2 * before.output


def test_run_limits_exist_for_the_dev_rfp(config: Config) -> None:
    assert config.limits.run("dev", "free").requests == 60
    assert config.limits.run("dev", "local").active_minutes == 60
    with pytest.raises(KeyError):
        config.limits.run("dev", "unknown")


def test_every_profile_has_a_call_timeout(config: Config) -> None:
    for profile in config.models.profiles:
        assert config.limits.call.timeout_for(profile) > 0, profile
    assert config.limits.call.timeout_for("local") > config.limits.call.timeout_for("free")


def test_every_profile_has_a_concurrency(config: Config) -> None:
    for profile in config.models.profiles:
        assert config.limits.concurrency_for(profile) >= 1, profile
    assert config.limits.concurrency_for("local") == 1  # Ollama serves one request at a time
    with pytest.raises(KeyError):
        config.limits.concurrency_for("unknown")


def test_the_paid_profile_mirrors_free_with_its_own_limits(config: Config) -> None:
    """CH-82: the free models under the paid key, with a row in every limits table."""
    for role, free in config.models.profiles["free"].items():
        paid = config.models.role("paid", role)
        assert (paid.provider, paid.model) == (free.provider, free.model)
        assert (paid.fallback, paid.thinking) == (free.fallback, free.thinking)
    assert config.limits.run("dev", "paid") == config.limits.run("dev", "free")
    assert config.limits.run("hero", "paid") == config.limits.run("hero", "free")
    assert config.limits.call.timeout_for("paid") == config.limits.call.timeout_for("free")
    assert config.limits.concurrency_for("paid") == 4
    for tier in ("free", "paid"):
        quota = config.limits.quota_for("gemini", tier, "gemini-3.5-flash-lite")
        assert quota is not None and quota.rpd > 0, tier
    free = config.limits.quota_for("gemini", "free", "gemini-3.5-flash-lite")
    paid = config.limits.quota_for("gemini", "paid", "gemini-3.5-flash-lite")
    assert free is not None and free.daily == "observe", "Google's own 429 decides (ADR-029)"
    assert paid is not None and (paid.rpm, paid.rpd, paid.daily) == (4000, 150_000, "enforce")
    assert config.limits.quota_for("ollama", "free", "qwen3.5:4b") is None


def test_every_cue_and_lint_pattern_compiles(config: Config) -> None:
    patterns = [p for kind in config.cues.kinds.values() for p in kind]
    patterns += [p for rule in config.lint.rules for p in rule.patterns]
    patterns += [p for rule in config.lint.contract for p in rule.patterns]
    patterns += config.ingest.suspect_patterns
    for pattern in patterns:
        assert re.compile(pattern, re.IGNORECASE)
    assert re.search(config.cues.kinds["MODAL"][0], "The Supplier shall keep records")
    assert re.search(config.lint.rules[0].patterns[0], "an appropriate response")


def test_lint_rule_ids_are_unique_and_templates_name_known_fields(config: Config) -> None:
    ids = [r.id for r in config.lint.rules] + [c.id for c in config.lint.contract]
    ids += list(config.lint.checks)
    assert len(ids) == len(set(ids))
    for rule in config.lint.rules:
        assert rule.question and "{requirement_id}" in rule.question


def test_a_pattern_that_does_not_compile_names_its_file_and_rule() -> None:
    with pytest.raises(ValidationError, match=r"config/cues\.yaml: cue kind MODAL"):
        CuesConfig.model_validate({"kinds": {"MODAL": ["("]}, "table_row_headers": []})
    bad = {
        "rules": [{"id": "vague", "kind": "VAGUE", "severity": "question", "patterns": ["(?P<x"]}],
        "contract": [],
        "units": ["day"],
        "checks": {},
    }
    with pytest.raises(ValidationError, match=r"config/lint\.yaml: rule vague"):
        LintConfig.model_validate(bad)
    with pytest.raises(ValidationError, match="unknown cue kinds"):
        CuesConfig.model_validate({"kinds": {"SMELL": ["x"]}, "table_row_headers": []})


def test_every_destination_names_its_hosts_and_whether_it_is_local(config: Config) -> None:
    """ADR-026: the egress register."""
    for name, destination in config.egress.destinations.items():
        assert destination.hosts, name
        assert isinstance(destination.local, bool), name
    assert config.egress.destinations["gemini"].local is False
    for local in ("ollama", "phoenix", "docling"):
        assert config.egress.destinations[local].local is True
        assert "localhost" in config.egress.destinations[local].hosts


def test_the_notebooklm_destination_is_remote_whatever_its_host(config: Config) -> None:
    """ADR-036: the server runs on this machine but forwards every query to Google."""
    notebooklm = config.egress.destinations["notebooklm"]
    assert notebooklm.local is False and notebooklm.receives == "queries"
    assert "127.0.0.1" in notebooklm.hosts and "host.docker.internal" in notebooklm.hosts


def test_the_research_server_names_its_package_and_binds_loopback(config: Config) -> None:
    server = config.research.servers["notebooklm"]
    assert isinstance(server, HttpServer)
    assert server.url.startswith("http://127.0.0.1:") and server.package and server.version


def test_no_server_is_pinned_before_its_pins_are_written(config: Config) -> None:
    """Until `bidwright research pin` runs, the pins name no tool, so every call is refused."""
    pins = config.pins.servers["notebooklm"]
    if not pins.tools:
        assert pins.server is None and pins.package is None


def _research(**changes: object) -> dict[str, object]:
    base: dict[str, object] = {
        "mode": "pack",
        "packs_dir": "research_packs",
        "selection": {"min_keyword_matches": 2},
        "jobs": {
            "max_per_run": 2,
            "mode": "deep",
            "wait_minutes": 20,
            "poll_seconds": 30,
            "import": "cited",
        },
        "questions": {"max_per_run": 6, "max_matches": 8, "match_share": 0.5, "min_terms": 2},
        "outbound": {"max_shared_words": 7},
        "servers": {},
        "tiers": {1: [".gov"], "default": 4},
    }
    return base | changes


def test_an_unknown_research_mode_fails_startup() -> None:
    assert ResearchConfig.model_validate(_research()).mode == "pack"
    with pytest.raises(ValidationError):
        ResearchConfig.model_validate(_research(mode="web"))


def test_tiers_take_keys_one_to_three_and_a_default_from_one_to_four() -> None:
    tiers = TiersConfig.model_validate({1: [".gov"], 3: ["bcs.org"], "default": 4})
    assert tiers.hosts == {1: [".gov"], 3: ["bcs.org"]} and tiers.default == 4
    with pytest.raises(ValidationError, match="tiers keys must be 1 to 3"):
        TiersConfig.model_validate({4: ["example.org"], "default": 4})
    with pytest.raises(ValidationError):
        TiersConfig.model_validate({1: [".gov"], "default": 5})


def test_a_server_entry_is_http_or_stdio() -> None:
    stdio = {"transport": "stdio", "command": "python", "timeout_s": 5, "tool_timeout_s": 5}
    parsed = ResearchConfig.model_validate(_research(servers={"fake": stdio}))
    assert parsed.servers["fake"].transport == "stdio"
    with pytest.raises(ValidationError):
        ResearchConfig.model_validate(_research(servers={"fake": {"transport": "sse"}}))
