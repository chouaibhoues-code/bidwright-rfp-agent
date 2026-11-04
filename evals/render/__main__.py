"""`python -m evals.render <corpus> [...]`: render each corpus package, its hashes and its gold."""

import argparse

from evals.render.gold import write_gold
from evals.render.package import INPUTS_DIR, MANIFEST, record_hash, render_package
from evals.render.spec import REPO_ROOT, load_spec

__all__ = ["INPUTS_DIR", "MANIFEST", "main", "record_hash"]


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="python -m evals.render", description=__doc__)
    parser.add_argument("corpora", nargs="+", help="corpus names under evals/corpus/")
    args = parser.parse_args(argv)
    for corpus in args.corpora:
        spec = load_spec(corpus)
        digests = render_package(spec)
        gold = write_gold(spec)
        files = ", ".join(f"{name} sha256:{digest[:12]}" for name, digest in digests.items())
        print(f"{corpus}: {files}, {gold.relative_to(REPO_ROOT)}")


if __name__ == "__main__":
    main()
