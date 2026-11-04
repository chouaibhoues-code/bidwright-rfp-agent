"""`lint`: requirement-quality checks and contract flags, in code (Iteration 1, step 13).

`run_lint` reads the quotes of the `BINDING` and `OPTIONAL` requirements, the `predictions()`
of `graph/nodes.py`, and finds:
- the pattern rules of `config/lint.yaml` (`VAGUE`, `ESCAPE`, `OPEN_LIST`, `TBD`);
- `MISSING_UNIT`: a number within the 3 tokens after "within", "at least", "no more than",
  "up to", "maximum" or "minimum", with no unit from the file's `units` in the 2 tokens after
  it or on the number itself, as in "99.9%" or "10GB";
- `BROKEN_REFERENCE`: a "Section 4.2", "Clause 4.2", "Annex B", "Appendix B" or "Schedule B"
  reference, by the `REFERENCE` cue's two patterns, matched with their capitals, that resolves
  to nothing: a section or clause number resolves when a section path segment of any document
  starts with it; an annex, appendix or schedule resolves when a document's title or file
  name holds the phrase, case-insensitively and with `_` or `-` read as spaces, or a section
  heading starts with it;
- `NON_SINGULAR`: two modal cues joined by "and" or "or", or a quote of two or more sentences;
- `UNDEFINED_TERM`: a phrase of 2 to 4 words that each begin with a capital letter, whose first
  word does not start a sentence, that occurs at least twice in the frozen text and is not a
  defined term, compared case-insensitively.
Tokens are whitespace-separated, so "99.9%" is one token, and a finding's `src_id` is its
requirement's first passage, the quote's. Severities and question templates come from the
file. Contract flags run over every passage: one flag per passage and category, with the
passage text cut at 300 characters, always `NEEDS_LEGAL_REVIEW`.

A coded check that raises on a quote is skipped for that quote and logged, and the caller's
`skipped` list gets "lint: <check> skipped on <requirement id>", which ends the run DEGRADED.
`lint` writes `lint_findings.jsonl` and `contract_flags.jsonl`.
"""

import logging
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from bidwright.candidates import cut
from bidwright.config import Config, compile_patterns
from bidwright.ingest import display_text, split_sentences
from bidwright.schemas import (
    QUOTE_MAX_CHARS,
    ContractFlag,
    ControlRegister,
    DefinedTerm,
    LintFinding,
    Passage,
    Requirement,
)
from bidwright.verify import SPELLED

log = logging.getLogger(__name__)

PREDICTED = ("BINDING", "OPTIONAL")
TRIGGERS = (
    ("within",),
    ("at", "least"),
    ("no", "more", "than"),
    ("up", "to"),
    ("maximum",),
    ("minimum",),
)
NUMBER_TOKEN = re.compile(r"^[(\[]?[$€£]?\d[\d,.]*")
EDGE = ".,;:()[]\"'"
CAPITALIZED = re.compile(r"[A-Z][\w'&-]*")
SENTENCE_START = re.compile(r"(?:^|[.!?:;]\s+)$")


@dataclass(frozen=True)
class LintContext:
    """What the coded checks read besides the quote."""

    config: Config
    frozen_text: str
    section_paths: frozenset[str]
    documents: tuple[str, ...]  # titles and file names, lowercase, `_` and `-` as spaces
    terms: frozenset[str]  # defined terms, lowercase
    modal: tuple[re.Pattern[str], ...]
    references: tuple[re.Pattern[str], ...]


Check = Callable[[str, LintContext], list[str]]


# --- the coded checks -----------------------------------------------------------------------


def _bare(token: str) -> str:
    return token.strip(EDGE).lower()


def _is_number(token: str) -> bool:
    bare = _bare(token)
    return bool(NUMBER_TOKEN.match(token.strip("\"'"))) or bare in SPELLED


def _singular(word: str) -> str:
    return word[:-1] if word.endswith("s") and len(word) > 2 else word


def _units(config: Config) -> tuple[set[str], set[tuple[str, ...]]]:
    """The unit words, one-word units apart from two-word ones such as "working day"."""
    single: set[str] = set()
    multi: set[tuple[str, ...]] = set()
    for unit in config.lint.units:
        words = tuple(unit.lower().split())
        if len(words) == 1:
            single.add(words[0])
        else:
            multi.add(words)
    return single, multi


def _is_unit(words: Sequence[str], single: set[str], multi: set[tuple[str, ...]]) -> bool:
    """Whether the tokens open with a unit, a plural one included."""
    if not words:
        return False
    if words[0] in single or _singular(words[0]) in single:
        return True
    if len(words) < 2:
        return False
    second = _singular(words[1])
    return (words[0], second) in multi or (_singular(words[0]), second) in multi


def _attached_unit(token: str, single: set[str]) -> bool:
    """A unit written on the number itself: "99.9%", "10GB", "£5", "200ms"."""
    rest = re.sub(r"[\d,.()\[\]]", "", token.strip(EDGE + "\"'"))
    return bool(rest) and (rest.lower() in single or rest[0] in "$€£" or rest[-1] == "%")


def missing_unit(quote: str, context: LintContext) -> list[str]:
    tokens = quote.split()
    lowered = [_bare(t) for t in tokens]
    single, multi = _units(context.config)
    found: list[str] = []
    for start in range(len(tokens)):
        for trigger in TRIGGERS:
            end = start + len(trigger)
            if tuple(lowered[start:end]) != trigger:
                continue
            for index in range(end, min(end + 3, len(tokens))):
                if not _is_number(tokens[index]):
                    continue
                after = [w for w in lowered[index + 1 : index + 3] if w]
                if not _attached_unit(tokens[index], single) and not _is_unit(after, single, multi):
                    found.append(" ".join(tokens[start : index + 1]).strip(EDGE))
                break
    return list(dict.fromkeys(found))


NUMBERED = re.compile(r"(?:(?:section|clause)\s+)?\d", re.IGNORECASE)


def _numbered(segment: str, label: str) -> bool:
    """Whether a heading carries the number: "4.2 Signing", "4.2. Signing" or "Section 4.2"."""
    pattern = rf"(?:(?:section|clause)\s+)?{re.escape(label)}\.?(?:\s|$)"
    return re.match(pattern, segment, re.IGNORECASE) is not None


def _resolves(reference: str, context: LintContext) -> bool:
    kind, _, label = reference.partition(" ")
    if kind.lower() in ("section", "clause"):
        if not any(NUMBERED.match(segment) for segment in context.section_paths):
            return True  # no heading carries a number, as with Word's numbering: no check
        return any(_numbered(segment, label) for segment in context.section_paths)
    phrase = reference.lower()
    if any(phrase in document for document in context.documents):
        return True
    return any(segment.lower().startswith(phrase) for segment in context.section_paths)


def broken_reference(quote: str, context: LintContext) -> list[str]:
    found = [
        match.group(0)
        for pattern in context.references
        for match in pattern.finditer(quote)
        if not _resolves(match.group(0), context)
    ]
    return list(dict.fromkeys(found))


def non_singular(quote: str, context: LintContext) -> list[str]:
    spans = sorted({match.span() for pattern in context.modal for match in pattern.finditer(quote)})
    found = []
    for (_, first_end), (second_start, second_end) in zip(spans, spans[1:], strict=False):
        between = quote[first_end:second_start]
        if re.search(r"\b(?:and|or)\b", between, re.IGNORECASE):
            start = max(0, quote.rfind(" ", 0, first_end - 1) + 1)
            found.append(quote[start:second_end])
    sentences = split_sentences(quote)
    if len(sentences) >= 2:
        start, end = sentences[1]
        found.append(quote[start:end])
    return list(dict.fromkeys(found))


def undefined_term(quote: str, context: LintContext) -> list[str]:
    found = []
    words = list(CAPITALIZED.finditer(quote))
    index = 0
    while index < len(words):
        run = [words[index]]
        while index + len(run) < len(words):
            following = words[index + len(run)]
            gap = quote[run[-1].end() : following.start()]
            if gap != " ":
                break
            run.append(following)
        index += len(run)
        if not 2 <= len(run) <= 4:
            continue
        before = quote[: run[0].start()]
        if SENTENCE_START.search(before) or (
            run[0].start() > 0 and quote[run[0].start() - 1].isalnum()
        ):
            continue
        phrase = quote[run[0].start() : run[-1].end()]
        if phrase.lower() in context.terms:
            continue
        if context.frozen_text.count(phrase) >= 2:
            found.append(phrase)
    return list(dict.fromkeys(found))


CHECKS: dict[str, Check] = {
    "missing-unit": missing_unit,
    "broken-reference": broken_reference,
    "non-singular": non_singular,
    "undefined-term": undefined_term,
}


# --- the run ----------------------------------------------------------------------------------


def lint_context(
    config: Config,
    passages: Sequence[Passage],
    terms: Sequence[DefinedTerm],
    register: ControlRegister | None,
    frozen_text: str | None = None,
) -> LintContext:
    segments = {segment for p in passages for segment in p.section_path.split(" > ") if segment}
    documents = tuple(
        re.sub(r"[_-]+", " ", text).lower()
        for entry in (register.documents if register else [])
        for text in (entry.title, entry.file)
    )
    references = tuple(
        re.compile(pattern)
        for pattern in config.cues.kinds.get("REFERENCE", [])
        if "Annex" in pattern or "Section" in pattern
    )
    return LintContext(
        config=config,
        frozen_text=frozen_text if frozen_text is not None else "\n".join(p.text for p in passages),
        section_paths=frozenset(segments),
        documents=documents,
        terms=frozenset(term.term.lower() for term in terms),
        modal=tuple(
            compile_patterns(config.cues.kinds.get("MODAL", []), "config/cues.yaml: MODAL")
        ),
        references=references,
    )


def run_lint(
    requirements: Sequence[Requirement],
    passages: Sequence[Passage],
    terms: Sequence[DefinedTerm],
    register: ControlRegister | None,
    config: Config,
    *,
    frozen_text: str | None = None,
    checks: Mapping[str, Check] | None = None,
    skipped: list[str] | None = None,
) -> tuple[list[LintFinding], list[ContractFlag]]:
    """Findings on the predicted requirements' quotes, and contract flags on every passage.

    `frozen_text` is the run's `frozen.txt`; without it the passages are joined. `checks`
    replaces the coded checks by name, for tests. A coded check that raises on a quote is
    skipped for that quote, and `skipped` gets one line for it."""
    context = lint_context(config, passages, terms, register, frozen_text)
    coded = {**CHECKS, **(checks or {})}
    rules = [
        (rule, compile_patterns(rule.patterns, f"config/lint.yaml: rule {rule.id}"))
        for rule in config.lint.rules
    ]
    findings: list[LintFinding] = []

    def add(rule: str, kind: str, requirement: Requirement, match: str, severity: str) -> None:
        findings.append(
            LintFinding.model_validate(
                {
                    "id": f"LF-{len(findings) + 1:04d}",
                    "rule": rule,
                    "kind": kind,
                    "requirement_id": requirement.id,
                    "src_id": requirement.src_ids[0],
                    "match": match,
                    "severity": severity,
                }
            )
        )

    for requirement in requirements:
        if requirement.disposition not in PREDICTED:
            continue
        quote = display_text(requirement.quote)
        for rule, patterns in rules:
            matches = [m.group(0) for p in patterns for m in p.finditer(quote)]
            for match in dict.fromkeys(matches):
                add(rule.id, rule.kind, requirement, match, rule.severity)
        for name, check in config.lint.checks.items():
            function = coded.get(name)
            if function is None:
                continue
            try:
                matches = function(quote, context)
            except Exception as exc:  # noqa: BLE001 - a broken check skips one quote, never the run
                line = f"lint: {name} skipped on {requirement.id}"
                log.warning("%s (%s: %s)", line, type(exc).__name__, exc)
                if skipped is not None:
                    skipped.append(line)
                continue
            for match in matches:
                add(name, check.kind, requirement, match, check.severity)
    return findings, contract_flags(passages, config)


def contract_flags(passages: Sequence[Passage], config: Config) -> list[ContractFlag]:
    """One flag per passage and category, from the first rule of that category that matches."""
    rules = [
        (rule, compile_patterns(rule.patterns, f"config/lint.yaml: contract rule {rule.id}"))
        for rule in config.lint.contract
    ]
    flags: list[ContractFlag] = []
    for passage in passages:
        text = display_text(passage.text)
        seen: set[str] = set()
        for rule, patterns in rules:
            if rule.category in seen:
                continue
            words = [m.group(0) for p in patterns for m in p.finditer(text)]
            if not words:
                continue
            seen.add(rule.category)
            flags.append(
                ContractFlag(
                    id=f"CF-{len(flags) + 1:03d}",
                    category=rule.category,
                    src_id=passage.id,
                    quote=cut(text, QUOTE_MAX_CHARS),
                    why=f"{rule.id}: {', '.join(dict.fromkeys(words))}",
                )
            )
    return flags


def write_lint(
    run_dir: Path, findings: Sequence[LintFinding], flags: Sequence[ContractFlag]
) -> None:
    """`lint_findings.jsonl` and `contract_flags.jsonl`; `lint` is their only writer."""
    run_dir.mkdir(parents=True, exist_ok=True)
    for name, rows in (("lint_findings.jsonl", findings), ("contract_flags.jsonl", flags)):
        body = "".join(row.model_dump_json() + "\n" for row in rows)
        (run_dir / name).write_text(body, encoding="utf-8", newline="\n")


__all__ = ["CHECKS", "LintContext", "contract_flags", "lint_context", "run_lint", "write_lint"]
