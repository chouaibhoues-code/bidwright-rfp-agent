"""The `consolidate` cluster rule, ADR-019, in code only (Iteration 1, step 14).

1. Members are the `BINDING` and `OPTIONAL` requirements.
2. The base key is the document and the first segment of the section path.
3. A base cluster over 12 members splits by the second segment, and any piece still over 12
   into runs of 12 in reading order.
4. Links, applied in this order, each merge checked against the cap after the previous one:
   an addendum member whose quote or passage names a section of the main document ("Section 4"
   or "Clause 4.2") links to the first cluster, in reading order, that holds a passage of that
   section; any other member that names a section links the same way, in any document; one
   that names an annex, appendix or schedule links to the first cluster of the document whose
   title or file name holds that phrase; and two members of different clusters whose content
   words have a Jaccard of 0.6 or more link as possible duplicates. The cluster linked to
   receives; for duplicates, the one earlier in reading order does.
5. Two linked clusters merge if the union has at most 12 members; otherwise the other
   cluster's members join the receiving cluster as read-only context, at most 8, nearest in
   reading order to its first member first.
6. A one-member cluster with no link and no context becomes a group in code; every other
   cluster goes to the model. Groups are numbered `RG-001` onward in the reading order of
   their first members.
7. Every cluster that holds an addendum member, or links to a cluster that does, gets the
   RFP's own order-of-precedence passages.
No step removes a requirement: every member ends in exactly one cluster.
"""

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

from bidwright.config import ClusterLimits
from bidwright.graph.nodes import PREDICTIONS, content_stems
from bidwright.ingest import display_text
from bidwright.schemas import ControlRegister, Passage, Requirement

SECTION_REFERENCE = re.compile(r"\b(?:Section|Clause) (\d+(?:\.\d+)*)\b")
ANNEX_REFERENCE = re.compile(r"\b(?:Annex|Appendix|Schedule) [A-Z0-9]+\b")
PRECEDENCE = re.compile(
    r"order of precedence|shall prevail|takes? precedence"
    r"|in the event of (?:any )?(?:conflict|inconsistency)",
    re.IGNORECASE,
)


@dataclass
class Cluster:
    members: list[str]  # requirement ids, in reading order
    context: list[str] = field(default_factory=list)
    linked: bool = False
    addendum: bool = False  # holds an addendum member or links to a cluster that does
    group_id: str = ""

    @property
    def to_model(self) -> bool:
        return len(self.members) > 1 or bool(self.context) or self.linked


def jaccard(left: set[str], right: set[str]) -> float:
    return len(left & right) / len(left | right) if left | right else 0.0


class _Builder:
    def __init__(
        self,
        requirements: Sequence[Requirement],
        passages: Mapping[str, Passage],
        register: ControlRegister | None,
        limits: ClusterLimits,
    ) -> None:
        self.limits = limits
        self.passages = passages
        order = {src: n for n, src in enumerate(passages)}
        self.members = sorted(
            (r for r in requirements if r.disposition in PREDICTIONS),
            key=lambda r: (order.get(r.src_ids[0], 0), r.id),
        )
        self.by_id = {r.id: r for r in self.members}
        self.rank = {r.id: n for n, r in enumerate(self.members)}
        roles = {e.doc_id: e.role for e in register.documents} if register else {}
        self.addendum = {
            r.id for r in self.members if roles.get(self._first(r).doc_id) == "addendum"
        }
        self.main = (
            {e.doc_id for e in register.documents if e.role == "main"} if register else set()
        )
        self.documents = [
            (e.doc_id, re.sub(r"[_-]+", " ", f"{e.title} {e.file}").lower())
            for e in (register.documents if register else [])
        ]
        self.clusters: list[Cluster] = []
        self.owner: dict[str, int] = {}

    def _first(self, requirement: Requirement) -> Passage:
        return self.passages[requirement.src_ids[0]]

    def _segments(self, requirement: Requirement) -> list[str]:
        return self._first(requirement).section_path.split(" > ")

    def _text(self, requirement: Requirement) -> str:
        return f"{requirement.quote} {display_text(self._first(requirement).text)}"

    # --- steps 1 to 3 ---------------------------------------------------------------------------

    def base(self) -> None:
        cap = self.limits.max_members
        groups: dict[tuple[str, str], list[str]] = {}
        for requirement in self.members:
            key = (self._first(requirement).doc_id, self._segments(requirement)[0])
            groups.setdefault(key, []).append(requirement.id)
        for ids in groups.values():
            if len(ids) <= cap:
                self._add(ids)
                continue
            pieces: dict[str, list[str]] = {}
            for rid in ids:
                segments = self._segments(self.by_id[rid])
                pieces.setdefault(segments[1] if len(segments) > 1 else "", []).append(rid)
            for piece in pieces.values():
                for start in range(0, len(piece), cap):
                    self._add(piece[start : start + cap])

    def _add(self, ids: list[str]) -> None:
        self.clusters.append(Cluster(members=list(ids), addendum=bool(set(ids) & self.addendum)))
        for rid in ids:
            self.owner[rid] = len(self.clusters) - 1

    # --- step 4: links ----------------------------------------------------------------------------

    def _holding_section(self, number: str, main_only: bool) -> str | None:
        """The first member, in reading order, whose passage sits in that section."""
        for requirement in self.members:
            passage = self._first(requirement)
            if main_only and self.main and passage.doc_id not in self.main:
                continue
            if any(s.startswith(f"{number} ") for s in passage.section_path.split(" > ")):
                return requirement.id
        return None

    def _holding_document(self, phrase: str) -> str | None:
        """The first member of the document whose title or file name holds the phrase."""
        wanted = [doc for doc, names in self.documents if phrase.lower() in names]
        for requirement in self.members:
            if self._first(requirement).doc_id in wanted:
                return requirement.id
        return None

    def links(self) -> list[tuple[str, str]]:
        """(member, receiving member) pairs, in the rule's order of link kinds. A link names
        a member of the receiving cluster, so it still finds that cluster after a merge."""
        found: list[tuple[str, str]] = []
        for addendum_pass in (True, False):
            for requirement in self.members:
                if (requirement.id in self.addendum) != addendum_pass:
                    continue
                for match in SECTION_REFERENCE.finditer(self._text(requirement)):
                    target = self._holding_section(match.group(1), main_only=addendum_pass)
                    if target is not None:
                        found.append((requirement.id, target))
        for requirement in self.members:
            for match in ANNEX_REFERENCE.finditer(self._text(requirement)):
                target = self._holding_document(match.group(0))
                if target is not None:
                    found.append((requirement.id, target))
        stems = {r.id: content_stems(r.quote) for r in self.members}
        for index, left in enumerate(self.members):
            for right in self.members[index + 1 :]:
                if jaccard(stems[left.id], stems[right.id]) >= self.limits.duplicate_jaccard:
                    found.append((right.id, left.id))
        return found

    def apply(self, links: list[tuple[str, str]]) -> None:
        for member, receiver in links:
            source, target = self.owner[member], self.owner[receiver]
            if source == target:
                continue
            giver, taker = self.clusters[source], self.clusters[target]
            giver.linked = taker.linked = True
            if giver.addendum or taker.addendum:
                giver.addendum = taker.addendum = True
            if len(giver.members) + len(taker.members) <= self.limits.max_members:
                taker.members = sorted(taker.members + giver.members, key=self.rank.__getitem__)
                self._attach(taker, giver.context)
                for rid in giver.members:
                    self.owner[rid] = target
                giver.members = []
                giver.context = []
            else:
                self._attach(taker, giver.members)
        self.clusters = [c for c in self.clusters if c.members]
        for index, cluster in enumerate(self.clusters):
            for rid in cluster.members:
                self.owner[rid] = index

    def _attach(self, taker: Cluster, extra: list[str]) -> None:
        anchor = self.rank[taker.members[0]]
        pool = {c for c in taker.context + extra if c not in taker.members}
        nearest = sorted(pool, key=lambda rid: (abs(self.rank[rid] - anchor), self.rank[rid]))
        taker.context = sorted(nearest[: self.limits.max_context], key=self.rank.__getitem__)

    def build(self) -> list[Cluster]:
        self.base()
        self.apply(self.links())
        self.clusters.sort(key=lambda c: self.rank[c.members[0]])
        for number, cluster in enumerate(self.clusters, start=1):
            cluster.group_id = f"RG-{number:03d}"
        return self.clusters


def build_clusters(
    requirements: Sequence[Requirement],
    passages: Mapping[str, Passage],
    register: ControlRegister | None,
    limits: ClusterLimits,
) -> list[Cluster]:
    """The clusters of the predicted requirements, numbered as groups in reading order."""
    return _Builder(requirements, passages, register, limits).build()


def precedence_passages(passages: Sequence[Passage]) -> list[Passage]:
    """The RFP's own order-of-precedence passages."""
    return [p for p in passages if PRECEDENCE.search(display_text(p.text))]


__all__ = ["Cluster", "build_clusters", "jaccard", "precedence_passages"]
