"""The profile's preconditions, checked at the run entry before the run folder exists.

`execute` calls `check_preconditions` in `live` and `record` mode, so every caller of the run
entry meets the same rules and a run that cannot start leaves nothing behind (ADR-023):
- `record` takes corpus files only, on any profile, because cassettes quote the document and
  Git tracks `tests/cassettes/`;
- on `free`, the file is in the synthetic corpus, `inputs/CORPUS.sha256`, or the run passes
  the exact consent string, which the manifest records (ADR-010; D-05 proposes removing it);
- a backend exists for every provider the profile's roles use, so a missing key fails here,
  not at the first LLM call after ingest;
- on Ollama, the primary and the fallback model of every role are pulled, so a fallback is
  never a 404 forty minutes into a run.
The file is hashed once, and the digest serves the corpus lookup, the override line and the
manifest. A replayed run sends nothing to a provider, so it needs none of this.
"""

import hashlib
import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, runtime_checkable

from bidwright.config import Config
from bidwright.llm.types import Backend, LLMError

HOME = Path(os.environ.get("BIDWRIGHT_HOME", Path(__file__).resolve().parents[2]))
CORPUS_MANIFEST = HOME / "inputs" / "CORPUS.sha256"
CONSENT = "i-accept-free-tier-terms"
KEY_HINTS = {"gemini": "set GEMINI_API_KEY in .env"}
LIMIT_TIERS = ("dev", "hero")


class Refused(Exception):
    """The run must not start. The message says why and what to do instead."""


@runtime_checkable
class ModelLister(Protocol):
    """A backend that can say which models are present, as the Ollama adapter can."""

    def models(self) -> set[str]: ...


@dataclass(frozen=True)
class Preflight:
    """What the preconditions established about the input file."""

    overrides: list[str]  # the override lines the manifest logs
    corpus: str | None  # the entry in `inputs/CORPUS.sha256`, such as "dev/dev_rfp.pdf"
    digest: str | None  # the file's sha256, or None when nothing was checked (replay)

    @property
    def tier(self) -> str:
        """The limits tier in `config/limits.yaml`: the corpus file's own, or `dev`."""
        first = (self.corpus or "").split("/")[0]
        return first if first in LIMIT_TIERS else "dev"


def digest_of(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def corpus_entry(digest: str, manifest: Path = CORPUS_MANIFEST) -> str | None:
    """The corpus entry recorded for a sha256 digest, if any."""
    if not manifest.exists():
        return None
    for line in manifest.read_text(encoding="utf-8").splitlines():
        parts = line.split(maxsplit=1)
        if len(parts) == 2 and parts[0] == digest:
            return parts[1].strip()
    return None


def corpus_name(path: Path, manifest: Path = CORPUS_MANIFEST) -> str | None:
    """The corpus entry whose hash matches the file, if any."""
    return corpus_entry(digest_of(path), manifest)


def check_corpus(
    path: Path, profile: str, consent: str | None, manifest: Path = CORPUS_MANIFEST
) -> list[str]:
    """The overrides to log. Raises `Refused` for a non-corpus file on `free` without consent."""
    digest = digest_of(path)
    return _corpus_rule(path.name, digest, corpus_entry(digest, manifest), profile, consent)


def _corpus_rule(
    name: str, digest: str, entry: str | None, profile: str, consent: str | None
) -> list[str]:
    if consent is not None and consent != CONSENT:
        raise Refused(f"--allow-non-corpus takes exactly {CONSENT!r}")
    if profile != "free" or entry:
        return []
    if consent == CONSENT:
        return [f"allow-non-corpus: {name} sha256:{digest}"]
    raise Refused(
        f"{name} is not in the synthetic corpus, and the free tier's terms let the provider"
        " use prompt content. Run it with --profile local, or pass"
        f" --allow-non-corpus={CONSENT} if you accept those terms."
    )


def _tagged(model: str) -> str:
    """Ollama lists an untagged pull as `name:latest`."""
    return model if ":" in model else f"{model}:latest"


def check_preconditions(
    *,
    source: Path,
    profile: str,
    mode: str,
    consent: str | None,
    backends: Mapping[str, Backend],
    config: Config,
) -> Preflight:
    """What the run may log and rely on. Raises `Refused` when the run must not start."""
    if mode == "replay":
        return Preflight([], None, None)
    if not source.is_file():
        raise Refused(f"{source} is not a file")
    digest = digest_of(source)
    entry = corpus_entry(digest)
    if mode == "record" and entry is None:
        raise Refused(
            f"{source.name} is not in the synthetic corpus. record writes into tests/cassettes,"
            " which Git tracks, so it records corpus files only, on any profile. Use"
            " bidwright run instead."
        )
    overrides = _corpus_rule(source.name, digest, entry, profile, consent)
    try:
        roles = config.models.profiles[profile]
    except KeyError as exc:
        raise Refused(f"no models are configured for profile {profile!r}") from exc
    for role_name, role in roles.items():
        if role.provider not in backends:
            hint = KEY_HINTS.get(role.provider, f"configure a backend for {role.provider!r}")
            raise Refused(
                f"the {profile} profile needs a {role.provider} backend for its {role_name}"
                f" role: {hint}"
            )
    pulled: dict[str, set[str]] = {}
    for role in roles.values():
        backend = backends[role.provider]
        if not isinstance(backend, ModelLister):
            continue
        if role.provider not in pulled:
            try:
                pulled[role.provider] = {_tagged(name) for name in backend.models()}
            except LLMError as exc:
                raise Refused(f"{exc}; start it, or point OLLAMA_HOST at a running one") from exc
        for model in (role.model, role.fallback):
            if model and _tagged(model) not in pulled[role.provider]:
                raise Refused(
                    f"model {model!r} is not pulled, and the {profile} profile needs it as"
                    f" {role.provider}'s {'fallback' if model == role.fallback else 'primary'}"
                    f" model: run ollama pull {model} (in Compose: docker compose exec ollama"
                    f" ollama pull {model})"
                )
    return Preflight(overrides, entry, digest)


__all__ = [
    "CONSENT",
    "CORPUS_MANIFEST",
    "HOME",
    "Preflight",
    "Refused",
    "check_corpus",
    "check_preconditions",
    "corpus_entry",
    "corpus_name",
    "digest_of",
]
