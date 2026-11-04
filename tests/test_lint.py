"""`lint`: each rule on a sentence that should and one that should not trip it, references
that resolve and do not, every contract category, resilience to a broken check, and speed on
long random text."""

import re
import time
from pathlib import Path

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from bidwright.config import load_config
from bidwright.lint import CHECKS, contract_flags, lint_context, run_lint, write_lint
from bidwright.schemas import (
    ContractFlag,
    ControlRegister,
    DefinedTerm,
    DocumentEntry,
    LintFinding,
    Passage,
    Requirement,
)

CONFIG = load_config()
SECTIONS = ["4 Requirements > 4.2 Records", "Annex B Optional services", "15 Contract terms"]


def _passage(number: int, text: str, section: str = SECTIONS[0]) -> Passage:
    return Passage(
        id=f"SRC-{number:04d}",
        doc_id="doc",
        section_path=section,
        kind="sentence",
        text=text,
        start=number * 1000,
        end=number * 1000 + len(text),
    )


PASSAGES = [_passage(n + 1, f"Passage {n}.", section) for n, section in enumerate(SECTIONS)]
REGISTER = ControlRegister(
    package="hero",
    precedence_source="rules",
    documents=[
        DocumentEntry(
            doc_id="doc",
            file="hero_appendix_c_pricing.xlsx",
            sha256="0" * 64,
            format="xlsx",
            role="annex",
            title="Schedule 2 Service levels",
            precedence=2,
            pages=None,
            sanitized=True,
            parser="docling",
        )
    ],
)


def _requirement(quote: str, number: int = 1, disposition: str = "BINDING") -> Requirement:
    return Requirement.model_validate(
        {
            "id": f"REQ-{number:04d}",
            "doc_id": "doc",
            "statement": quote,
            "modality": "shall",
            "mandatory": disposition == "BINDING",
            "hazard": False,
            "disposition": disposition,
            "src_ids": ["SRC-0001"],
            "quote": quote,
            "quote_status": "VERBATIM_VERIFIED",
        }
    )


def _kinds(quote: str, frozen: str | None = None, terms: list[DefinedTerm] | None = None) -> dict:
    findings, _ = run_lint(
        [_requirement(quote)], PASSAGES, terms or [], REGISTER, CONFIG, frozen_text=frozen
    )
    found: dict[str, list[str]] = {}
    for finding in findings:
        found.setdefault(finding.kind, []).append(finding.match)
    return found


@pytest.mark.parametrize(
    ("kind", "fires", "quiet"),
    [
        (
            "VAGUE",
            "The Supplier shall provide appropriate training.",
            "The Supplier shall train 20 staff.",
        ),
        (
            "ESCAPE",
            "The Supplier shall reply where practicable.",
            "The Supplier shall reply within 2 days.",
        ),
        ("OPEN_LIST", "Formats include PDF, DOCX, etc.", "Formats are PDF and DOCX."),
        ("TBD", "The go-live date is TBD.", "The go-live date is 2027-04-01."),
        (
            "MISSING_UNIT",
            "The Supplier shall answer within 10.",
            "The Supplier shall answer within 10 working days.",
        ),
        (
            "MISSING_UNIT",
            "Keep at least 3 backups offsite.",
            "Keep availability of at least 99.9% each month.",
        ),
        (
            "NON_SINGULAR",
            "The Supplier shall host the service and shall support it.",
            "The Supplier shall host the service.",
        ),
        (
            "NON_SINGULAR",
            "The Supplier shall host it. Users must sign in.",
            "The Supplier shall host it for users.",
        ),
    ],
)
def test_each_rule_on_a_matching_and_a_quiet_sentence(kind: str, fires: str, quiet: str) -> None:
    assert kind in _kinds(fires), fires
    assert kind not in _kinds(quiet), quiet


def test_units_written_on_the_number_or_spelled_numbers_count() -> None:
    assert "MISSING_UNIT" not in _kinds("Respond within ten business days of a request.")
    assert "MISSING_UNIT" not in _kinds("Use no more than 10GB of storage.")
    assert _kinds("Reply within 72 of a request.")["MISSING_UNIT"] == ["within 72"]


@pytest.mark.parametrize(
    ("reference", "resolves"),
    [
        ("Section 4.2", True),
        ("Section 9.1", False),
        ("Clause 15", True),
        ("Clause 16", False),
        ("Annex B", True),
        ("Annex D", False),
        ("Appendix C", True),
        ("Appendix E", False),
        ("Schedule 2", True),
        ("Schedule 3", False),
    ],
)
def test_references_resolve_against_sections_titles_and_files(
    reference: str, resolves: bool
) -> None:
    found = _kinds(f"The Supplier shall comply with {reference} at all times.")
    assert ("BROKEN_REFERENCE" in found) is not resolves, found
    assert "BROKEN_REFERENCE" not in _kinds("The Supplier shall schedule maintenance weekly.")


def test_undefined_terms_need_two_uses_and_no_definition() -> None:
    quote = "The Supplier shall staff the Service Desk during Service Hours."
    frozen = f"{quote}\nThe Service Desk opens daily. Service Hours are listed below."
    assert _kinds(quote, frozen)["UNDEFINED_TERM"] == ["Service Desk", "Service Hours"]
    defined = [DefinedTerm(term="service hours", definition="x", src_id="SRC-0001")]
    assert _kinds(quote, frozen, defined)["UNDEFINED_TERM"] == ["Service Desk"]
    assert "UNDEFINED_TERM" not in _kinds(quote, quote), "used once"
    assert "UNDEFINED_TERM" not in _kinds("Service Desk staff shall log calls.", frozen * 2), (
        "the phrase starts the sentence"
    )


def test_findings_cover_predicted_requirements_only_and_number_in_order(tmp_path: Path) -> None:
    requirements = [
        _requirement("The Supplier shall provide appropriate training etc.", 1),
        _requirement("The Council may provide adequate rooms.", 2, "BACKGROUND"),
        _requirement("The Supplier should reply as far as possible.", 3, "OPTIONAL"),
    ]
    findings, flags = run_lint(requirements, PASSAGES, [], REGISTER, CONFIG)
    assert [f.id for f in findings] == [f"LF-{n:04d}" for n in range(1, len(findings) + 1)]
    assert {f.requirement_id for f in findings} == {"REQ-0001", "REQ-0003"}
    assert all(f.src_id == "SRC-0001" for f in findings)
    question = {f.kind: f.severity for f in findings}
    assert question == {"VAGUE": "question", "OPEN_LIST": "question", "ESCAPE": "question"}
    write_lint(tmp_path, findings, flags)
    lines = (tmp_path / "lint_findings.jsonl").read_text(encoding="utf-8").splitlines()
    assert [LintFinding.model_validate_json(line) for line in lines] == findings
    assert (tmp_path / "contract_flags.jsonl").exists()


@pytest.mark.parametrize(
    ("category", "text"),
    [
        ("LIABILITY", "The Supplier accepts unlimited liability for data loss."),
        ("INDEMNITY", "The Supplier shall indemnify the Council against all claims."),
        ("IP", "All intellectual property in the deliverables passes to the Council."),
        ("DATA", "The Supplier acts as data processor for personal data."),
        ("SERVICE_CREDITS", "Service credits apply when availability falls below target."),
        ("TERMINATION", "The Council may terminate for convenience on 30 days' notice."),
        ("FLOW_DOWN", "These terms flow down to every subcontractor."),
    ],
)
def test_each_contract_category_is_flagged_once_per_passage(category: str, text: str) -> None:
    flags = contract_flags([_passage(1, text), _passage(2, "The weather is fine.")], CONFIG)
    assert [(f.category, f.src_id) for f in flags] == [(category, "SRC-0001")]
    [flag] = flags
    assert flag.status == "NEEDS_LEGAL_REVIEW" and flag.quote == text
    assert flag.why.split(":")[0] in {rule.id for rule in CONFIG.lint.contract}
    assert ContractFlag.model_validate_json(flag.model_dump_json()) == flag


def test_lint_resilience(caplog: pytest.LogCaptureFixture) -> None:
    def broken(quote: str, context: object) -> list[str]:
        raise RuntimeError("a check bug")

    skipped: list[str] = []
    requirements = [_requirement("The Supplier shall answer within 10.", 7)]
    findings, _ = run_lint(
        requirements,
        PASSAGES,
        [],
        REGISTER,
        CONFIG,
        checks={"missing-unit": broken},
        skipped=skipped,
    )
    assert skipped == ["lint: missing-unit skipped on REQ-0007"]
    assert "missing-unit skipped" in caplog.text
    assert "MISSING_UNIT" not in {f.kind for f in findings}, "only that check is skipped"


PIECES = [*"abcdefghij ABCDEFGHIJ 0123456789 .,;:%£()-", "within ", "at least ", "Section 4."]
PIECES += ["Annex ", " shall ", " and "]
TEXT = st.lists(st.sampled_from(PIECES), min_size=2000, max_size=2000).map(
    lambda parts: "".join(parts)[:2000]
)


@settings(deadline=None, max_examples=25)
@given(TEXT)
def test_every_rule_finishes_on_long_random_text(text: str) -> None:
    context = lint_context(CONFIG, PASSAGES, [], REGISTER, frozen_text=text * 2)
    for name, check in CHECKS.items():
        start = time.perf_counter()
        check(text, context)
        assert time.perf_counter() - start < 0.05, name
    for rule in [*CONFIG.lint.rules, *CONFIG.lint.contract]:
        start = time.perf_counter()
        for pattern in rule.patterns:
            re.compile(pattern, re.IGNORECASE).findall(text)
        assert time.perf_counter() - start < 0.05, rule.id
