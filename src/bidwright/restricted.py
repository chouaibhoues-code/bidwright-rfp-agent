"""The restricted-name check (Iteration 2, step 13), shared by the repository hygiene test and
the research pack builder, so both flag exactly the same text.

Some names may never enter a committed file. The check compares salted SHA-256 hashes of a
text's tokens with a list of forbidden hashes, so neither this module nor the test holds the
names. The list comes from the environment variable `HYGIENE_HASHES`, a JSON object with a
`salt` and the hex digests under `sha256`; CI sets it from a secret. Without it the check
cannot run, and `RestrictedNames.from_environment` returns None.
"""

import hashlib
import json
import os
import re
from dataclasses import dataclass

VARIABLE = "HYGIENE_HASHES"


def tokens(text: str) -> set[str]:
    """Words, their path parts, adjacent path-part pairs, and their -_. fragments, lowercased."""
    cleaned = text.replace("\\", "/")
    for char in "`'\"()[]{}<>,;|":
        cleaned = cleaned.replace(char, " ")
    found: set[str] = set()
    for raw in cleaned.split():
        word = raw.strip(".:").lower()
        if not word:
            continue
        stems = [part.removesuffix(".git") for part in word.split("/") if part]
        found.add(word)
        found.update(stems)
        found.update(f"{left}/{right}" for left, right in zip(stems, stems[1:], strict=False))
        for stem in stems:
            found.update(fragment for fragment in re.split(r"[-_.]", stem) if fragment)
    return found


@dataclass(frozen=True)
class RestrictedNames:
    salt: str
    forbidden: frozenset[str]

    @classmethod
    def from_environment(cls) -> "RestrictedNames | None":
        """The list in `HYGIENE_HASHES`, or None when the variable is unset or empty."""
        raw = os.environ.get(VARIABLE)
        if not raw:
            return None
        spec = json.loads(raw)
        return cls(str(spec["salt"]), frozenset(str(h) for h in spec["sha256"]))

    def flags(self, text: str) -> bool:
        """Whether any token of `text` is a restricted name."""
        return any(
            hashlib.sha256((self.salt + token).encode()).hexdigest() in self.forbidden
            for token in tokens(text)
        )


__all__ = ["VARIABLE", "RestrictedNames", "tokens"]
