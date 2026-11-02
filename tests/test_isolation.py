"""Producer code never imports the evaluation harness, and never names its gold or corpus."""

import ast
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src" / "bidwright"


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names |= {alias.name.split(".")[0] for alias in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module.split(".")[0])
    return names


def test_src_bidwright_never_imports_evals() -> None:
    offenders = [p.relative_to(SRC).as_posix() for p in SRC.rglob("*.py") if "evals" in _imports(p)]
    assert offenders == []


def test_src_bidwright_never_reads_gold_or_corpus_paths() -> None:
    offenders = [
        p.relative_to(SRC).as_posix()
        for p in SRC.rglob("*.py")
        if "evals/gold" in p.read_text(encoding="utf-8")
        or "evals/corpus" in p.read_text(encoding="utf-8")
    ]
    assert offenders == []
