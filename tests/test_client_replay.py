"""Record, replay, parsing and ledger reporting in the LLM client."""

from pathlib import Path

import pytest

from bidwright.config import load_config
from bidwright.llm.client import LLMClient
from bidwright.llm.replay import CassetteStore
from bidwright.llm.simulator import ProviderSimulator
from bidwright.llm.types import CassetteMissing, Message
from bidwright.schemas import ExtractResult, LedgerEntry
from tests.llm_fakes import CALL, FakeBackend

MESSAGES = [Message("system", "Extract obligations."), Message("user", "passages")]


def test_record_then_replay_without_a_backend(tmp_path: Path) -> None:
    store = CassetteStore(tmp_path)
    config = load_config()
    live = LLMClient(config, "free", {"gemini": FakeBackend()}, mode="record", cassettes=store)
    recorded = live.complete("extract", MESSAGES, ExtractResult, **CALL)
    replay = LLMClient(config, "free", mode="replay", cassettes=store)
    replayed = replay.complete("extract", MESSAGES, ExtractResult, **CALL)
    assert replayed.replayed and not recorded.replayed
    assert replayed.text == recorded.text
    assert replayed.usage == recorded.usage
    assert isinstance(replayed.parsed, ExtractResult)


def test_a_missing_cassette_is_an_error(tmp_path: Path) -> None:
    replay = LLMClient(load_config(), "free", mode="replay", cassettes=CassetteStore(tmp_path))
    with pytest.raises(CassetteMissing):
        replay.complete("extract", MESSAGES, ExtractResult, **CALL)


def test_schema_failures_are_reported_not_raised() -> None:
    client = LLMClient(load_config(), "free", {"gemini": FakeBackend(text='{"items": "nope"}')})
    completion = client.complete("extract", MESSAGES, ExtractResult, **CALL)
    assert completion.parsed is None and completion.parse_error


def test_each_call_reports_one_ledger_entry_with_a_shadow_price() -> None:
    entries: list[LedgerEntry] = []
    client = LLMClient(
        load_config(), "free", {"gemini": FakeBackend()}, run_id="run-1", on_ledger=entries.append
    )
    client.complete("extract", MESSAGES, ExtractResult, **CALL)
    assert len(entries) == 1
    entry = entries[0]
    assert entry.run_id == "run-1" and entry.model == "gemini-3.5-flash-lite"
    assert entry.cost_usd == 0.0  # the free tier
    assert entry.shadow_cost_usd == pytest.approx((1000 * 0.30 + 200 * 2.50) / 1_000_000)


def test_record_mode_needs_a_store() -> None:
    with pytest.raises(ValueError, match="cassette store"):
        LLMClient(load_config(), "free", mode="record")


def test_replay_finds_a_run_that_fell_back(tmp_path: Path) -> None:
    store = CassetteStore(tmp_path)
    config = load_config()
    timeouts = ProviderSimulator(
        FakeBackend(), [{"call": n, "fault": "timeout"} for n in range(1, 5)]
    )
    recorder = LLMClient(
        config, "free", {"gemini": timeouts}, mode="record", cassettes=store, sleep=lambda _: None
    )
    recorded = recorder.complete("extract", MESSAGES, ExtractResult, **CALL)
    replayed = LLMClient(config, "free", mode="replay", cassettes=store).complete(
        "extract", MESSAGES, ExtractResult, **CALL
    )
    assert recorded.model == replayed.model == "gemini-3.1-flash-lite"
    assert replayed.replayed and replayed.provider == "gemini"


def test_a_prompt_decoding_block_overrides_the_role_default() -> None:
    backend = FakeBackend()
    client = LLMClient(load_config(), "free", {"gemini": backend})
    decoding = {"gemini": {"thinking": "medium"}, "ollama": {"think": True}}
    client.complete("reason", MESSAGES, ExtractResult, **CALL, decoding=decoding)
    client.complete("reason", MESSAGES, ExtractResult, **CALL)
    assert [r.settings for r in backend.requests] == [{"thinking": "medium"}, {"thinking": "low"}]


def test_decoding_is_part_of_the_cassette_key(tmp_path: Path) -> None:
    store = CassetteStore(tmp_path)
    config = load_config()
    medium = {"gemini": {"thinking": "medium"}}
    recorder = LLMClient(config, "free", {"gemini": FakeBackend()}, mode="record", cassettes=store)
    recorder.complete("reason", MESSAGES, ExtractResult, **CALL, decoding=medium)
    replay = LLMClient(config, "free", mode="replay", cassettes=store)
    assert replay.complete("reason", MESSAGES, ExtractResult, **CALL, decoding=medium).replayed
    with pytest.raises(CassetteMissing):
        replay.complete("reason", MESSAGES, ExtractResult, **CALL)


@pytest.mark.parametrize(
    "decoding",
    [
        {"gemini": {"temperature": 0}},
        {"gemini": {"model": "gemini-3.6-flash"}},
        {"gemini": {"thinking": "maximum"}},
    ],
)
def test_bad_decoding_settings_are_rejected(decoding: dict[str, dict[str, object]]) -> None:
    client = LLMClient(load_config(), "free", {"gemini": FakeBackend()})
    with pytest.raises(ValueError):
        client.complete("reason", MESSAGES, ExtractResult, **CALL, decoding=decoding)
