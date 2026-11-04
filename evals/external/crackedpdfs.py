"""`guard` on the CrackedPDFs test split (Iteration 1, step 19).

CrackedPDFs pairs benign PDFs with copies that carry an injected instruction, from 15 attack
families, and adds matched benign copies whose structure changes with nothing injected. It is
MIT-licensed and published on Hugging Face as `volkthienpreecha/crackedpdfs`; this adapter
reads revision 245bc98 (V-02). It runs guard's PDF scan, `scan_pdf`, on each file of the
published test split, with no parser and no model call, and predicts a positive when the scan
finds hidden text: at least one `pdf_*` finding. A file the scan refuses (encrypted,
unreadable or over the page limit) reaches no parser either, so it counts as a positive too,
and the report counts it apart. `guard` detects hidden content, not intent: an instruction in
visible text is outside its reach by design, and a benign file that hides text is flagged.

The data never enters the repository. Prepare a folder outside it once:
  1. download `data/metadata.jsonl`, `data/splits.json`, `pdfs/benign.tar.gz` and
     `pdfs/injected.tar.gz` at the revision above;
  2. check them against `evals/external/BENCHMARKS.sha256`;
  3. extract both archives into the folder, so that `benign/` and `injected/` sit beside
     `data/`.
Then run `bidwright-eval external crackedpdfs --data <folder>`. Only the scores are written,
to `evals/results/external/crackedpdfs.md`.
"""

import hashlib
import json
import statistics
import time
from collections import Counter
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path

from bidwright.config import IngestConfig, load_config
from bidwright.guard.limits import PolicyBlocked
from bidwright.guard.pdf import scan_pdf
from evals.score import ROOT

NAME = "CrackedPDFs"
REVISION = "245bc98ec7e838346ee6fd5bdf5fed1b16d2a3e5"
SOURCE = "https://huggingface.co/datasets/volkthienpreecha/crackedpdfs"
BENCHMARKS = Path(__file__).with_name("BENCHMARKS.sha256")
RESULTS = ROOT / "evals" / "results" / "external" / "crackedpdfs.md"
DATA_FILES = ("data/metadata.jsonl", "data/splits.json")
# F1 on the same test split, from the paper (a preprint), confirmed at source (Research-Register).
PUBLISHED = (
    ("Hybrid structural detector", 0.960),
    ("Rule baseline", 0.623),
    ("PromptGuard on extracted text", 0.390),
)


class BenchmarkRefused(Exception):
    """The benchmark folder is missing, inside the repository, or does not match its hashes."""


@dataclass(frozen=True)
class Item:
    pdf_id: str
    path: str
    label: int
    attack_family: str
    confounder: str
    regime: str


@dataclass(frozen=True)
class Outcome:
    item: Item
    positive: bool
    refused: bool
    seconds: float
    kinds: frozenset[str] = frozenset()


def _inside(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
    except ValueError:
        return False
    return True


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def check_files(folder: Path, checksums: Path = BENCHMARKS) -> None:
    """Every listed file that is present must match its hash, and the two data files must be
    present. The archives may be deleted once they are extracted."""
    for line in checksums.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        digest, name = line.split(maxsplit=1)
        name = name.lstrip("*")
        path = folder / name
        if not path.exists():
            if name in DATA_FILES:
                raise BenchmarkRefused(f"{path} is missing; prepare the folder first")
            continue
        if _sha256(path) != digest:
            raise BenchmarkRefused(f"{name} does not match {checksums.name}")


def load_test_split(folder: Path) -> list[Item]:
    """The published test split, in `data/splits.json` order, with labels from the metadata."""
    splits = json.loads((folder / "data" / "splits.json").read_text(encoding="utf-8"))
    wanted = list(splits["test_ids"])
    keep = set(wanted)
    rows: dict[str, Item] = {}
    with (folder / "data" / "metadata.jsonl").open(encoding="utf-8") as handle:
        for line in handle:
            row = json.loads(line)
            if row["pdf_id"] in keep:
                rows[row["pdf_id"]] = Item(
                    pdf_id=row["pdf_id"],
                    path=row["file_path"],
                    label=int(row["label"]),
                    attack_family=row.get("attack_family") or "none",
                    confounder=row.get("benign_confounder_family") or "none",
                    regime=row.get("rendering_regime") or "unknown",
                )
    missing = [pdf_id for pdf_id in wanted if pdf_id not in rows]
    if missing:
        raise BenchmarkRefused(f"the metadata lacks {len(missing)} test ids, e.g. {missing[0]}")
    return [rows[pdf_id] for pdf_id in wanted]


def predict(path: Path, ingest: IngestConfig) -> tuple[bool, bool, frozenset[str]]:
    """(flagged, refused, kinds): flagged when the scan finds hidden text, of the `pdf_*`
    kinds returned, or refuses the file."""
    try:
        scan = scan_pdf(path, ingest, path.name)
    except PolicyBlocked:
        return True, True, frozenset()
    kinds = frozenset(finding.kind for finding in scan.findings)
    return bool(kinds), False, kinds


def run_items(
    folder: Path,
    items: Iterable[Item],
    ingest: IngestConfig,
    say: Callable[[str], None] = print,
) -> list[Outcome]:
    outcomes = []
    for number, item in enumerate(items, start=1):
        path = folder / item.path
        if not path.is_file():
            raise BenchmarkRefused(f"{path} is missing; extract both archives into {folder}")
        start = time.perf_counter()
        positive, refused, kinds = predict(path, ingest)
        outcomes.append(Outcome(item, positive, refused, time.perf_counter() - start, kinds))
        if number % 250 == 0:
            say(f"{number} files scanned")
    return outcomes


def metrics(outcomes: list[Outcome]) -> dict[str, float]:
    tp = sum(1 for o in outcomes if o.positive and o.item.label == 1)
    fp = sum(1 for o in outcomes if o.positive and o.item.label == 0)
    fn = sum(1 for o in outcomes if not o.positive and o.item.label == 1)
    tn = sum(1 for o in outcomes if not o.positive and o.item.label == 0)
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    seconds = [o.seconds for o in outcomes] or [0.0]
    return {
        "files": len(outcomes),
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "tn": tn,
        "precision": precision,
        "recall": recall,
        "f1": f1,
        "accuracy": (tp + tn) / len(outcomes) if outcomes else 0.0,
        "refused": sum(1 for o in outcomes if o.refused),
        "refused_benign": sum(1 for o in outcomes if o.refused and o.item.label == 0),
        "seconds_mean": statistics.fmean(seconds),
        "seconds_median": statistics.median(seconds),
    }


def _rates(outcomes: list[Outcome], label: int, key: Callable[[Item], str]) -> list[str]:
    """Table rows of flagged files, out of all files with this label, grouped by `key`."""
    total: Counter[str] = Counter()
    flagged: Counter[str] = Counter()
    for o in outcomes:
        if o.item.label == label:
            total[key(o.item)] += 1
            flagged[key(o.item)] += int(o.positive)
    return [
        f"| {group} | {flagged[group]} | {total[group]} | {flagged[group] / total[group]:.1%} |"
        for group in sorted(total)
    ]


def _kinds(outcomes: list[Outcome]) -> list[str]:
    """Table rows: files with each kind of hidden text, injected and benign."""
    found: dict[int, Counter[str]] = {0: Counter(), 1: Counter()}
    for o in outcomes:
        found[o.item.label].update(o.kinds)
    return [
        f"| `{kind}` | {found[1][kind]:,} | {found[0][kind]:,} |"
        for kind in sorted(found[0].keys() | found[1].keys())
    ]


def report(outcomes: list[Outcome]) -> str:
    m = metrics(outcomes)
    injected, benign = int(m["tp"] + m["fn"]), int(m["fp"] + m["tn"])
    return "\n".join(
        [
            f"# `guard` on the {NAME} test split",
            "",
            f"Revision `{REVISION[:7]}` of [{NAME}]({SOURCE}), MIT License, checked against"
            " `evals/external/BENCHMARKS.sha256`, and scored by"
            " `bidwright-eval external crackedpdfs`. `guard`'s PDF scan ran on each file with no"
            " parser and no model call. A file counts as flagged when the scan found hidden text"
            " or refused the file. Only these scores are committed.",
            "",
            "| Measure | Value |",
            "|---|---|",
            f"| Files | {int(m['files']):,}: {injected:,} injected, {benign:,} benign |",
            f"| Injected files flagged (true positives) | {int(m['tp']):,} |",
            f"| Benign files flagged (false positives) | {int(m['fp']):,} |",
            f"| Precision | {m['precision']:.3f} |",
            f"| Recall | {m['recall']:.3f} |",
            f"| F1 | {m['f1']:.3f} |",
            f"| Accuracy | {m['accuracy']:.3f} |",
            f"| Files the scan refused, counted as flagged | {int(m['refused']):,}, of which"
            f" {int(m['refused_benign']):,} benign |",
            f"| Seconds per file, mean and median | {m['seconds_mean']:.3f} and"
            f" {m['seconds_median']:.3f} |",
            "",
            "Published F1 on the same split, from the CrackedPDFs paper (a preprint), beside this"
            " run:",
            "",
            "| Detector | F1 |",
            "|---|---|",
            *[f"| {name} | {value:.3f} |" for name, value in PUBLISHED],
            f"| `guard`'s PDF scan, this run | {m['f1']:.3f} |",
            "",
            "`guard` was not tuned on this data, and it looks for hidden text, not for intent."
            " The benchmark's benign confounders hide harmless text with the same techniques as"
            " the injected files, so a detector of hidden text flags them too, and precision"
            " carries that cost. In Bidwright a flagged file is not rejected: its hidden text is"
            " quarantined and shown to a person, so a false positive costs review time, not a"
            " lost requirement. An instruction in plain visible text is outside `guard`'s reach"
            " by design; other controls carry that case: `ingest` flags passages that read like"
            " an instruction to a model, the document text sits inside delimiters, the tool"
            " gateway checks every call, and every output stays `UNREVIEWED_DRAFT`.",
            "",
            "## Files with each kind of hidden text",
            "",
            "A file can hold more than one kind. `pdf_off_page` is text whose box lies wholly"
            " outside the page's crop box.",
            "",
            "| Kind | Injected files | Benign files |",
            "|---|---|---|",
            *_kinds(outcomes),
            "",
            "## Injected files flagged, by rendering regime",
            "",
            "| Rendering regime | Flagged | Of | Recall |",
            "|---|---|---|---|",
            *_rates(outcomes, 1, lambda item: item.regime),
            "",
            "## Injected files flagged, by attack family",
            "",
            "| Attack family | Flagged | Of | Recall |",
            "|---|---|---|---|",
            *_rates(outcomes, 1, lambda item: item.attack_family),
            "",
            "## Benign files flagged, by confounder family",
            "",
            "| Confounder family | Flagged | Of | Share flagged |",
            "|---|---|---|---|",
            *_rates(outcomes, 0, lambda item: item.confounder),
            "",
        ]
    )


def run(
    folder: Path,
    out: Path = RESULTS,
    *,
    checksums: Path = BENCHMARKS,
    ingest: IngestConfig | None = None,
    repository: Path = ROOT,
    say: Callable[[str], None] = print,
) -> Path:
    """Check the folder, scan the test split and write the scores to `out`."""
    if not folder.is_dir():
        raise BenchmarkRefused(f"{folder} is not a folder")
    if _inside(folder, repository):
        raise BenchmarkRefused(f"{folder} is inside the repository; keep benchmark data outside")
    check_files(folder, checksums)
    items = load_test_split(folder)
    say(f"{len(items)} test files; scanning")
    outcomes = run_items(folder, items, ingest or load_config().ingest, say)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(report(outcomes), encoding="utf-8", newline="\n")
    return out


__all__ = [
    "BENCHMARKS",
    "BenchmarkRefused",
    "Item",
    "Outcome",
    "check_files",
    "load_test_split",
    "metrics",
    "predict",
    "report",
    "run",
    "run_items",
]
