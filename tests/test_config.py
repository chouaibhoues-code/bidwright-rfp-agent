"""Config tests: every file loads, validates, and agrees with the others."""

from datetime import date

import pytest

from bidwright import schemas
from bidwright.config import Config, load_config

TOOLS_IN_0A = {"search_rfp", "date_calc"}


@pytest.fixture(scope="module")
def config() -> Config:
    return load_config()


def test_every_file_loads(config: Config) -> None:
    assert config.models.profiles
    assert config.limits.batch_size == 20
    assert config.agents.agents
    assert config.thresholds.block
    assert config.pricing.models


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
        assert set(agent.tools) <= TOOLS_IN_0A


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
        config.limits.run("dev", "paid")


def test_every_profile_has_a_call_timeout(config: Config) -> None:
    for profile in config.models.profiles:
        assert config.limits.call.timeout_for(profile) > 0, profile
    assert config.limits.call.timeout_for("local") > config.limits.call.timeout_for("free")


def test_every_profile_has_a_concurrency(config: Config) -> None:
    for profile in config.models.profiles:
        assert config.limits.concurrency_for(profile) >= 1, profile
    assert config.limits.concurrency_for("local") == 1  # Ollama serves one request at a time
    with pytest.raises(KeyError):
        config.limits.concurrency_for("paid")
