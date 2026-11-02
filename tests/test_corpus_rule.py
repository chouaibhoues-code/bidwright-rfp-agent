"""On `free`, only corpus files run, unless the user gives the exact consent string."""

from pathlib import Path

import pytest

from bidwright.cli import CONSENT, Refused, check_corpus, corpus_name
from tests.node_fakes import DEV_RFP


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
