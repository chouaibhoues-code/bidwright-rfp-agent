"""`python -m evals.render <corpus> [...]`: render each corpus RFP, its hash and its gold."""

import argparse
import hashlib
from pathlib import Path

from evals.render.gold import write_gold
from evals.render.pdf import render_pdf
from evals.render.spec import REPO_ROOT, load_spec

INPUTS_DIR = REPO_ROOT / "inputs"
MANIFEST = INPUTS_DIR / "CORPUS.sha256"


def record_hash(path: Path, manifest: Path = MANIFEST) -> str:
    """Add or replace the file's line in the manifest, in `sha256sum` format, sorted by path."""
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    relative = path.relative_to(manifest.parent).as_posix()
    entries: dict[str, str] = {}
    if manifest.exists():
        for line in manifest.read_text(encoding="utf-8").splitlines():
            if line.strip():
                value, name = line.split(maxsplit=1)
                entries[name.strip()] = value
    entries[relative] = digest
    lines = "".join(f"{entries[name]}  {name}\n" for name in sorted(entries))
    manifest.write_text(lines, encoding="utf-8", newline="\n")
    return digest


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="python -m evals.render", description=__doc__)
    parser.add_argument("corpora", nargs="+", help="corpus names under evals/corpus/")
    args = parser.parse_args(argv)
    for corpus in args.corpora:
        spec = load_spec(corpus)
        pdf = INPUTS_DIR / spec.output
        render_pdf(spec, pdf)
        digest = record_hash(pdf)
        gold = write_gold(spec)
        where = f"{pdf.relative_to(REPO_ROOT)} sha256:{digest[:12]}"
        print(f"{corpus}: {where}, {gold.relative_to(REPO_ROOT)}")


if __name__ == "__main__":
    main()
