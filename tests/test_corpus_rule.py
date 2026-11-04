"""On `free`, only corpus files run, unless the user gives the exact consent string. The rule
sits at the run entry, so `execute` refuses before a run folder exists, and the manifest of a
run that used the override records it."""

import hashlib
from pathlib import Path

import pytest

from bidwright.graph.build import execute
from bidwright.preflight import CONSENT, Refused, check_corpus, corpus_name
from bidwright.schemas import RunManifest
from tests.node_fakes import DEV_RFP, RuleBackend


@pytest.fixture
def stranger(tmp_path: Path) -> Path:
    path = tmp_path / "my_tender.pdf"
    path.write_bytes(b"%PDF-1.4 not in the corpus")
    return path


def test_corpus_files_are_recognized_by_hash(tmp_path: Path) -> None:
    assert corpus_name(DEV_RFP) == "dev/dev_rfp.pdf"
    renamed = tmp_path / "renamed.pdf"
    renamed.write_bytes(DEV_RFP.read_bytes())
    assert corpus_name(renamed) == "dev/dev_rfp.pdf"
    assert check_corpus(DEV_RFP, "free", None) == []


def test_a_non_corpus_file_is_refused_on_free(stranger: Path) -> None:
    with pytest.raises(Refused, match="--profile local"):
        check_corpus(stranger, "free", None)


def test_the_override_works_and_is_logged(stranger: Path) -> None:
    [note] = check_corpus(stranger, "free", CONSENT)
    assert note.startswith("allow-non-corpus: my_tender.pdf sha256:")


def test_a_wrong_consent_string_is_refused(stranger: Path) -> None:
    with pytest.raises(Refused, match="exactly"):
        check_corpus(stranger, "free", "yes")


def test_local_never_refuses(stranger: Path) -> None:
    assert check_corpus(stranger, "local", None) == []


def test_free_refuses_a_non_corpus_file_at_the_run_entry(stranger: Path, tmp_path: Path) -> None:
    with pytest.raises(Refused, match="--profile local"):
        execute(
            docling_mode="replay",
            source=stranger,
            profile="free",
            outputs=tmp_path / "out",
            backends={"gemini": RuleBackend()},
        )
    assert not (tmp_path / "out").exists()


def test_the_override_runs_a_non_corpus_file_and_the_manifest_records_it(
    tmp_path: Path, client_root: Path
) -> None:
    twin = tmp_path / "my_tender.pdf"
    twin.write_bytes(DEV_RFP.read_bytes() + b"\n% a trailing comment changes the hash only\n")
    assert corpus_name(twin) is None
    result = execute(
        docling_mode="replay",
        source=twin,
        profile="free",
        outputs=tmp_path / "out",
        backends={"gemini": RuleBackend()},
        consent=CONSENT,
        run_id="override",
    )
    assert result.status == "COMPLETED", result.reason
    manifest = RunManifest.model_validate_json(
        (result.run_dir / "run_manifest.json").read_text(encoding="utf-8")
    )
    digest = hashlib.sha256(twin.read_bytes()).hexdigest()
    assert manifest.overrides == [f"allow-non-corpus: my_tender.pdf sha256:{digest}"]
    assert manifest.data_class == "client", "D-05: the override never makes a file synthetic"
    assert [(d.file, d.sha256) for d in manifest.documents] == [("my_tender.pdf", digest)]
