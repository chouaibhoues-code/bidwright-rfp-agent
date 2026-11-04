"""The Docling client: one conversion per file through docling-serve's `POST /v1/convert/file`
(C7-08), in the three modes of the LLM client (Iteration 1, step 7).

- `live` calls the service, with 3 retries on connection errors and 5xx responses;
- `record` also saves the response as a cassette, `tests/cassettes/docling/<key>.json`;
- `replay` reads the cassette and never opens a connection.
The key is the sha256 of the file's bytes joined with the sha256 of the conversion options,
serialized as in the LLM cassette rule. A `failure` status ends the run UNRECOVERABLE_FAULT;
`partial_success` continues, and the run is marked DEGRADED with the file named.

    python -m bidwright.parsers.docling_client record <file or folder>...

converts corpus files with the configured options and writes their cassettes, sending the
guard's sanitized copy of a DOCX or XLSX, as the parser does.
"""

import argparse
import hashlib
import json
import os
import random
import sys
import tempfile
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

import httpx

from bidwright.config import Config, load_config
from bidwright.preflight import HOME

Mode = Literal["live", "record", "replay"]
CASSETTES = HOME / "tests" / "cassettes" / "docling"
URL_VARIABLE = "DOCLING_URL"
MIME = {
    ".pdf": "application/pdf",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
}


class DoclingError(Exception):
    """The Docling service could not convert a file."""


class DoclingFailed(DoclingError):
    """A conversion failed, after its retries when the failure was transient."""


class DoclingCassetteMissing(DoclingError):
    """Replay found no cassette for a file and options."""


def docling_url(config: Config) -> str:
    """`DOCLING_URL` overrides the configured URL; an empty variable means the default."""
    return os.environ.get(URL_VARIABLE, "").strip() or config.ingest.docling.url


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def cassette_key(data: bytes, options: dict[str, Any]) -> str:
    joined = {
        "file": hashlib.sha256(data).hexdigest(),
        "options": hashlib.sha256(_canonical(options).encode()).hexdigest(),
    }
    return "sha256:" + hashlib.sha256(_canonical(joined).encode()).hexdigest()


def form_fields(options: dict[str, Any]) -> dict[str, str | list[str]]:
    """Options as multipart form fields: booleans as `true` or `false`, lists repeated."""
    fields: dict[str, str | list[str]] = {}
    for name, value in options.items():
        if isinstance(value, bool):
            fields[name] = "true" if value else "false"
        elif isinstance(value, list | tuple):
            fields[name] = [str(v) for v in value]
        else:
            fields[name] = str(value)
    return fields


@dataclass
class DoclingClient:
    mode: Mode
    url: str
    options: dict[str, Any]
    timeout_s: float = 180.0
    retries: int = 3
    store: Path = CASSETTES
    transport: httpx.BaseTransport | None = None
    sleep: Callable[[float], None] = time.sleep
    backoff_base_s: float = 2.0
    backoff_cap_s: float = 30.0
    calls: list[str] = field(default_factory=list)  # the files sent to the service

    @classmethod
    def from_config(cls, config: Config, mode: Mode, **kwargs: Any) -> "DoclingClient":
        settings = config.ingest.docling
        return cls(
            mode=mode,
            url=docling_url(config),
            options=dict(settings.options),
            timeout_s=settings.timeout_s,
            retries=settings.retries,
            backoff_base_s=config.limits.call.backoff_base_s,
            backoff_cap_s=config.limits.call.backoff_cap_s,
            **kwargs,
        )

    def _http(self, timeout: float) -> httpx.Client:
        return httpx.Client(base_url=self.url, timeout=timeout, transport=self.transport)

    def healthy(self, timeout_s: float) -> bool:
        """Whether `GET /health` answers within the timeout. Replay never asks."""
        try:
            with self._http(timeout_s) as client:
                return client.get("/health").status_code == 200
        except httpx.HTTPError:
            return False

    def convert(self, path: Path) -> dict[str, Any]:
        """`{"status", "errors", "document": {"json_content"}}` for one file."""
        data = path.read_bytes()
        key = cassette_key(data, self.options)
        cassette = self.store / f"{key.removeprefix('sha256:')}.json"
        if self.mode == "replay":
            if not cassette.exists():
                raise DoclingCassetteMissing(f"no Docling cassette {key} for {path.name}")
            recorded = json.loads(cassette.read_text(encoding="utf-8"))
            return {k: recorded[k] for k in ("status", "errors", "document")}
        body = self._post(path.name, data)
        result = {
            "status": body.get("status"),
            "errors": body.get("errors") or [],
            "document": {"json_content": (body.get("document") or {}).get("json_content")},
        }
        if result["status"] == "failure" or result["document"]["json_content"] is None:
            raise DoclingFailed(f"Docling could not convert {path.name}: {result['errors']}")
        if self.mode == "record":
            cassette.parent.mkdir(parents=True, exist_ok=True)
            record = {
                "key": key,
                "file": path.name,
                "options": self.options,
                **result,
                "recorded": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
            }
            cassette.write_text(
                json.dumps(record, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n"
            )
        return result

    def _post(self, name: str, data: bytes) -> dict[str, Any]:
        mime = MIME.get(Path(name).suffix.lower(), "application/octet-stream")
        last = ""
        for attempt in range(self.retries + 1):
            try:
                self.calls.append(name)
                with self._http(self.timeout_s) as client:
                    response = client.post(
                        "/v1/convert/file",
                        files={"files": (name, data, mime)},
                        data=form_fields(self.options),
                    )
                if response.status_code < 500:
                    if response.status_code >= 400:
                        detail = response.text[:200]
                        raise DoclingFailed(
                            f"Docling refused {name}: HTTP {response.status_code} {detail}"
                        )
                    return response.json()
                last = f"HTTP {response.status_code}"
            except httpx.TransportError as exc:
                last = f"{type(exc).__name__}: {exc}"
            if attempt < self.retries:
                delay = min(self.backoff_cap_s, self.backoff_base_s * 2**attempt)
                self.sleep(random.uniform(0, delay))  # noqa: S311 - jitter, not security
        raise DoclingFailed(f"Docling did not convert {name} after {self.retries} retries: {last}")


def _sent_path(path: Path, run_dir: Path, config: Config) -> Path:
    """What the parser sends: the guard's sanitized copy of a DOCX or XLSX, a PDF as it is."""
    from bidwright.guard import run_guard

    result = run_guard([path], run_dir, config)
    return next(iter(result.sanitized.values()), path)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m bidwright.parsers.docling_client")
    sub = parser.add_subparsers(dest="command", required=True)
    record = sub.add_parser("record", help="convert corpus files and write Docling cassettes")
    record.add_argument("paths", nargs="+", type=Path)
    args = parser.parse_args(argv)
    from bidwright.preflight import corpus_name, package_documents

    config = load_config()
    client = DoclingClient.from_config(config, "record")
    if not client.healthy(config.ingest.docling.health_timeout_s):
        print(f"the Docling service at {client.url} does not answer", file=sys.stderr)
        return 2
    files = [d for p in args.paths for d in (package_documents(p) if p.is_dir() else [p])]
    for path in files:
        if corpus_name(path) is None:
            print(f"{path} is not in the synthetic corpus; cassettes hold corpus files only")
            return 2
    with tempfile.TemporaryDirectory() as tmp:
        for index, path in enumerate(files):
            sent = _sent_path(path, Path(tmp) / str(index), config)
            client.convert(sent)
            key = cassette_key(sent.read_bytes(), client.options)
            print(f"{path}: {key}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
