"""The profile's preconditions at the run entry: a missing key, a missing local model and an
unreachable Ollama are refused before a run folder exists; a replayed run needs none of it."""

from dataclasses import dataclass, field
from pathlib import Path

import pytest

from bidwright.config import Config, load_config
from bidwright.graph.build import execute
from bidwright.ingest import doc_id_for
from bidwright.llm.types import ProviderError, Request, Response
from bidwright.preflight import Preflight, Refused, check_preconditions, package_digest
from tests.node_fakes import DEV_RFP, RuleBackend


@dataclass
class FakeOllama:
    """Stands in for `OllamaBackend`: lists what is pulled, and is never called."""

    pulled: set[str] = field(default_factory=set)
    down: bool = False
    provider: str = "ollama"
    paid: bool = False

    def models(self) -> set[str]:
        if self.down:
            raise ProviderError("ollama at http://127.0.0.1:9 did not answer: refused")
        return set(self.pulled)

    def call(self, request: Request) -> Response:
        raise AssertionError("the preconditions must fail before any call")


def _check(**changes: object) -> Preflight:
    settings: dict[str, object] = {
        "source": DEV_RFP,
        "profile": "free",
        "mode": "live",
        "consent": None,
        "backends": {"gemini": RuleBackend()},
        "config": load_config(),
    }
    return check_preconditions(**(settings | changes))  # type: ignore[arg-type]


def test_a_missing_key_is_refused_before_the_run_folder_exists(tmp_path: Path) -> None:
    with pytest.raises(Refused, match="GEMINI_API_KEY"):
        execute(source=DEV_RFP, profile="free", outputs=tmp_path, backends={})
    assert list(tmp_path.iterdir()) == []


def test_the_paid_profile_names_its_own_key() -> None:
    with pytest.raises(Refused, match="GEMINI_PAID_API_KEY"):
        _check(profile="paid", backends={})


def test_a_run_with_no_model_call_needs_no_key_but_keeps_the_corpus_rule(tmp_path: Path) -> None:
    """B0 makes no model call, so `models=False` skips the backend checks, and nothing else."""
    assert _check(backends={}, models=False).data_class == "synthetic"
    stranger = tmp_path / "my_tender.pdf"
    stranger.write_bytes(b"%PDF-1.4 not in the corpus")
    with pytest.raises(Refused, match="--profile local"):
        _check(source=stranger, backends={}, models=False)


def test_a_missing_local_model_is_refused_with_the_pull_command(tmp_path: Path) -> None:
    ollama = FakeOllama(pulled={"qwen3.5:4b"})
    with pytest.raises(Refused, match=r"ollama pull qwen3\.5:2b") as refused:
        execute(source=DEV_RFP, profile="local", outputs=tmp_path, backends={"ollama": ollama})
    assert "fallback" in str(refused.value)
    assert list(tmp_path.iterdir()) == []


def test_the_local_profile_passes_when_both_models_are_pulled() -> None:
    ollama = FakeOllama(pulled={"qwen3.5:4b", "qwen3.5:2b"})
    found = _check(profile="local", backends={"ollama": ollama})
    assert found.overrides == [] and found.corpus == "dev/dev_rfp.pdf" and found.tier == "dev"
    assert found.digest and len(found.digest) == 64


def test_an_untagged_model_matches_the_latest_tag_ollama_lists() -> None:
    config = load_config()
    for role in config.models.profiles["local"].values():
        role.model, role.fallback = "llama3", None
    ollama = FakeOllama(pulled={"llama3:latest"})
    assert _check(profile="local", backends={"ollama": ollama}, config=config).overrides == []


def test_an_unreachable_ollama_is_refused() -> None:
    with pytest.raises(Refused, match="did not answer"):
        _check(profile="local", backends={"ollama": FakeOllama(down=True)})


def test_a_missing_file_is_refused(tmp_path: Path) -> None:
    with pytest.raises(Refused, match="is not a file"):
        _check(source=tmp_path / "missing.pdf")


@pytest.mark.parametrize("profile", ["free", "local"])
def test_record_takes_corpus_files_only_on_every_profile(tmp_path: Path, profile: str) -> None:
    """The record rule comes first, so `free` never answers with the consent override."""
    stranger = tmp_path / "client_tender.pdf"
    stranger.write_bytes(b"%PDF-1.4")
    backends = {"gemini": RuleBackend(), "ollama": FakeOllama(pulled={"qwen3.5:4b", "qwen3.5:2b"})}
    with pytest.raises(Refused, match="Git tracks"):
        _check(source=stranger, profile=profile, mode="record", backends=backends)


def test_a_replayed_run_needs_no_backend_and_no_corpus_check(tmp_path: Path) -> None:
    found = _check(source=tmp_path / "missing.pdf", mode="replay", backends={})
    assert found == Preflight([], None, None) and found.tier == "dev"


def test_an_unknown_profile_is_refused() -> None:
    config: Config = load_config()
    with pytest.raises(Refused, match="no models"):
        _check(profile="unknown", config=config)


HERO = DEV_RFP.parents[1] / "hero"
PULLED = {"ollama": FakeOllama(pulled={"qwen3.5:4b", "qwen3.5:2b"})}


def test_a_synthetic_folder_is_a_package_named_after_its_folder() -> None:
    """D-05: the folder name is the package id, and the first document sets the tier."""
    found = _check(source=HERO)
    assert found.package_id == "hero" and found.data_class == "synthetic"
    assert found.tier == "hero" and found.corpus == "hero/hero_addendum_1.pdf"
    assert [d.path.name for d in found.documents] == [
        "hero_addendum_1.pdf",
        "hero_annex_b_requirements.xlsx",
        "hero_rfp.pdf",
    ]
    assert found.digest == package_digest([d.sha256 for d in found.documents])


def _client_folder(tmp_path: Path) -> Path:
    folder = tmp_path / "Northwind confidential tender"
    folder.mkdir()
    (folder / "Northwind main tender.pdf").write_bytes(b"%PDF-1.4 a client document")
    (folder / "package.yaml").write_text("package: client\n", encoding="utf-8")
    return folder


def test_a_client_folder_is_refused_on_free(tmp_path: Path) -> None:
    with pytest.raises(Refused, match="--profile local"):
        _check(source=_client_folder(tmp_path))


def test_a_client_folder_on_local_gets_an_id_without_a_file_name(tmp_path: Path) -> None:
    found = _check(source=_client_folder(tmp_path), profile="local", backends=PULLED)
    assert found.data_class == "client" and found.package_id is not None
    assert found.package_id.startswith("pkg-") and len(found.package_id) == len("pkg-") + 8
    assert "northwind" not in found.package_id.lower()
    assert [d.path.name for d in found.documents] == ["Northwind main tender.pdf"]


def test_a_single_client_file_gets_a_doc_id(tmp_path: Path) -> None:
    path = tmp_path / "Northwind main tender.pdf"
    path.write_bytes(b"%PDF-1.4 a client document")
    found = _check(source=path, profile="local", backends=PULLED)
    assert found.package_id is not None and found.package_id.startswith("doc-")
    assert _check(source=DEV_RFP).package_id == doc_id_for(DEV_RFP)


def test_an_empty_folder_is_refused(tmp_path: Path) -> None:
    empty = tmp_path / "empty"
    empty.mkdir()
    (empty / "package.yaml").write_text("package: empty\n", encoding="utf-8")
    with pytest.raises(Refused, match="no documents"):
        _check(source=empty)


def test_a_tier_with_no_run_limits_for_the_profile_is_refused() -> None:
    with pytest.raises(Refused, match="no run limits for hero on local"):
        _check(source=HERO, profile="local", backends=PULLED)


class FakeDocling:
    """Stands in for `DoclingClient`: answers each health check as `answers` says, then as
    the last of them."""

    def __init__(self, up: bool, answers: list[bool] | None = None) -> None:
        self.answers = answers if answers is not None else [up]
        self.url = "http://127.0.0.1:9"
        self.asked = 0

    def healthy(self, timeout_s: float) -> bool:
        self.asked += 1
        return self.answers[min(self.asked, len(self.answers)) - 1]


def test_a_docling_run_is_refused_when_the_health_check_fails() -> None:
    down = FakeDocling(up=False)
    with pytest.raises(Refused, match="Docling service.*2 times"):
        _check(source=HERO, docling=down)
    assert down.asked == load_config().ingest.docling.health_attempts == 2
    assert _check(source=HERO, docling=FakeDocling(up=True)).package_id == "hero"


def test_a_docling_that_misses_its_first_health_check_is_asked_again() -> None:
    """An idle container answered its first request too late on 2026-11-10 (failure log)."""
    waking = FakeDocling(up=True, answers=[False, True])
    assert _check(source=HERO, docling=waking).package_id == "hero"
    assert waking.asked == 2


def test_a_replayed_run_asks_docling_nothing(tmp_path: Path) -> None:
    down = FakeDocling(up=False)
    _check(source=HERO, mode="replay", backends={}, docling=down)
    assert down.asked == 0


def test_a_missing_cerebras_or_groq_key_refuses_no_run(tmp_path: Path) -> None:
    """The assess role is routed (ADR-045): without its keys it takes the reason role's model."""
    config = load_config()
    preflight = check_preconditions(
        source=DEV_RFP,
        profile="free",
        mode="live",
        consent=None,
        backends={"gemini": RuleBackend()},
        config=config,
    )
    assert preflight.data_class == "synthetic"


def test_a_routed_role_whose_provider_is_present_needs_its_models_pulled() -> None:
    """A routed role needs no key, but when its provider's backend is there it serves the
    role, so a model it names and nobody pulled is refused before the run (code review)."""
    config = load_config()
    local = config.models.profiles["local"]
    local["assess"] = local["assess"].model_copy(update={"fallback": "qwen3.5:1b"})
    ollama = FakeOllama(pulled={"qwen3.5:4b", "qwen3.5:2b"})
    with pytest.raises(Refused, match=r"ollama pull qwen3\.5:1b"):
        _check(profile="local", backends={"ollama": ollama}, config=config)
