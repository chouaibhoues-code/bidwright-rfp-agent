"""Egress (ADR-026, D-05): every destination a run may reach, checked before the run starts.

`config/egress.yaml` lists each destination with its hosts, whether it is local, and what it
may receive. `execute` calls `check_run` after preflight, once the run's data class is known,
over the model backends the profile uses, the trace endpoint and the Docling URL:
- a host the register does not list for its destination is refused, on any run;
- on a client run, a remote destination is refused, except Gemini on a `free` run that passed
  the consent override, which ADR-026 keeps from ADR-010;
- a backend with no `host` attribute, as every test double, is local and passes.

A refused backend or Docling URL stops the run with `EgressRefused`, a `Refused`, so the run
leaves no folder. A refused trace endpoint does not stop it: spans go to `spans.jsonl`, and
`check_run` returns the refusal for `RunManifest.refused_destinations`.

From Iteration 2, `execute` also passes the research server when the research mode is `live`.
Its URL is `server_url`'s: the server entry's, unless `<NAME>_MCP_URL` names another, as
`NOTEBOOKLM_MCP_URL` does on the host. A refused research server names `--research pack`, which
needs no server; a stdio entry has no host to check, so it is refused on any run.
"""

import os
from collections.abc import Mapping
from urllib.parse import urlparse

from bidwright.config import EgressConfig, HttpServer, StdioServer, load_config
from bidwright.preflight import Refused

CONSENT_DESTINATION = "gemini"  # the one remote destination the consent override opens
DOCLING_DESTINATION = "docling"
TRACE_DESTINATION = "phoenix"
RESEARCH_DESTINATION = "notebooklm"  # the research server, and its entry in research.yaml
PACK_ADVICE = "Run it with --research pack, which needs no server."


class EgressRefused(Refused):
    """A destination the egress register does not allow for this run."""


def server_url(name: str, server: HttpServer) -> str:
    """The research server's URL: `<NAME>_MCP_URL` when set and not empty, else the entry's."""
    return os.environ.get(f"{name.upper()}_MCP_URL") or server.url


def hostname(address: str) -> str:
    """The lowercase host of a URL or of a bare host name, with any port removed."""
    parsed = urlparse(address if "://" in address else f"//{address}")
    return (parsed.hostname or "").lower()


def check(
    destination: str,
    host: str,
    data_class: str,
    *,
    register: EgressConfig | None = None,
    consent: bool = False,
    advice: str = "Run it with --profile local.",
) -> None:
    """Raise `EgressRefused` unless the register allows `host` for `destination` on a run of
    this data class. `consent` is true on a `free` run that passed the consent override, and
    `advice` ends a client run's refusal."""
    destinations = (register or load_config().egress).destinations
    entry = destinations.get(destination)
    name = hostname(host)
    if entry is None:
        raise EgressRefused(f"{destination} is not a destination in config/egress.yaml")
    if name not in {listed.lower() for listed in entry.hosts}:
        raise EgressRefused(
            f"{name or host!r} is not a host config/egress.yaml lists for {destination}"
        )
    if data_class == "client" and not entry.local:
        if consent and destination == CONSENT_DESTINATION:
            return
        raise EgressRefused(
            f"a client run reaches local destinations only, and {destination} at {name} is"
            f" remote. {advice}"
        )


def check_run(
    backends: Mapping[str, object],
    trace_endpoint: str | None,
    docling_url: str | None,
    data_class: str,
    *,
    register: EgressConfig | None = None,
    consent: bool = False,
    research: tuple[str, HttpServer | StdioServer] | None = None,
) -> list[str]:
    """Check a run's outbound channels; return the refused trace endpoint, if any, for the
    manifest. Backends are keyed by provider, which names their destination. `research` is the
    research server's name and entry, on a `live` run."""
    register = register or load_config().egress
    if research is not None:
        _check_research(*research, data_class, register)
    for provider, backend in backends.items():
        host = getattr(backend, "host", None)
        if host is None:
            continue
        check(provider, str(host), data_class, register=register, consent=consent)
    if docling_url:
        check(DOCLING_DESTINATION, docling_url, data_class, register=register)
    refused = []
    if trace_endpoint:
        try:
            check(TRACE_DESTINATION, trace_endpoint, data_class, register=register)
        except EgressRefused:
            refused.append(f"{TRACE_DESTINATION} at {hostname(trace_endpoint)}")
    return refused


def _check_research(
    name: str, server: HttpServer | StdioServer, data_class: str, register: EgressConfig
) -> None:
    if isinstance(server, StdioServer):
        raise EgressRefused(
            f"the research server {name} runs over stdio, so it has no host the register can"
            f" check; a run reaches research over HTTP only. {PACK_ADVICE}"
        )
    check(name, server_url(name, server), data_class, register=register, advice=PACK_ADVICE)


__all__ = ["EgressRefused", "check", "check_run", "hostname", "server_url"]
