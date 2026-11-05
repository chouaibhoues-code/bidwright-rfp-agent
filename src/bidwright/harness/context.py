"""`ContextManager`: what each packed LLM call sees, and the manifest that records it
(Iteration 1, step 9).

Three paths pack the model calls of Iteration 1, and each writes one manifest per call to
`context/<node>-<call_id>.json` in the run folder before the node makes the call:
- `pack` groups passages into `extract` packs, call ids `B01` onward, in reading order. A pack
  closes when it holds `batch_size` passages or when the next passage would pass the budget; a
  passage larger than the budget goes alone, and no passage is ever cut or dropped. Each pack
  carries its members' neighbors in their document, marked as context so they are never
  extracted twice, and the first `max_terms` defined terms, by first occurrence, that occur in
  its members. With no `batch_size`, as for EX0, every passage goes into one pack and the budget
  splits nothing; the manifest still reports the utilization against it.
- `pack_sections` groups `triage`'s section views into calls, `T01` onward, by the same budget
  rule, and `sections_in` gives back the sections of one call.
- `pack_cluster` checks one `consolidate` cluster task against its budget, under the group id; a
  task over the budget is a fault, since the cluster rule caps a cluster at 12 members.
- `pack_brief` (Iteration 2) groups the `EVALUATION` sections, then the `INSTRUCTION` sections,
  each whole and in document order, with the verified requirements their passages hold and the
  RFP profile, into `brief` calls, `F01` onward, by the same budget rule; a section larger than
  the budget goes alone. A manifest's `included_record_ids` names the requirements it holds.
- `record_manifest` (Iteration 2) writes the manifest of a call whose evidence is records or
  excerpts rather than packed passages, `discover`'s calls `D01` onward, naming them in
  `included_record_ids`.

Tokens are estimated as characters divided by `chars_per_token`, rounded up. A manifest's
`tokens_by_layer` takes `rules` (the system text less its examples), `examples` and `task` from
the prompt (`prompt_tokens`), and `evidence` from the call's data. `fixed_tokens` is the
prompt's share, so the evidence budget is `budget_tokens` less its total, and `utilization` is
the sum of the layers over `budget_tokens`. Every text a model sees comes from the run's
`TextView` (D-05); `None` means the frozen text, through `IdentityView`.
"""

import json
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from bidwright.candidates import cut
from bidwright.config import ContextLimits
from bidwright.harness.view import IdentityView, TextView
from bidwright.prompts import Prompt
from bidwright.schemas import (
    DEFINITION_MAX_CHARS,
    BriefSection,
    ClusterTask,
    ContextManifest,
    ContextPack,
    ContextPassageView,
    CueHit,
    DefinedTerm,
    LayerTokens,
    Passage,
    PassageView,
    Requirement,
    RequirementView,
    RfpProfile,
    SectionView,
    TermView,
    ZoneRecord,
)

CALL_PREFIX = {"extract": "B", "triage": "T", "brief": "F", "discover": "D"}
BRIEF_ZONES = ("EVALUATION", "INSTRUCTION")  # packed in this order
CONTEXT_DIR = "context"
_PACK_KEYS = len(json.dumps({"passages": [], "context": [], "terms": []}, separators=(",", ":")))
_SECTION_KEYS = len(json.dumps({"sections": []}, separators=(",", ":")))
_BRIEF_KEYS = len(
    json.dumps({"sections": [], "profile": {}, "requirements": []}, separators=(",", ":"))
)


class ContextOverflow(ValueError):
    """A cluster task over its budget, which the cluster rule's member cap should prevent."""


def estimate_tokens(chars: int, chars_per_token: int) -> int:
    """Characters divided by `chars_per_token`, rounded up."""
    return -(-chars // chars_per_token)


def prompt_tokens(prompt: Prompt, chars_per_token: int, task: str = "task") -> LayerTokens:
    """The prompt's own tokens, by layer, with no evidence: the `fixed_tokens` of a pack."""
    if task not in prompt.tasks:
        raise KeyError(f"{prompt.ref} has no <{task}> element")
    examples = len(prompt.examples)
    return LayerTokens(
        rules=estimate_tokens(len(prompt.system) - examples, chars_per_token),
        examples=estimate_tokens(examples, chars_per_token),
        task=estimate_tokens(len(prompt.tasks[task].template), chars_per_token),
    )


def _fixed(layers: LayerTokens) -> int:
    return layers.rules + layers.examples + layers.task


def _list_chars(items: Sequence[int]) -> int:
    """The serialized items of one JSON list, with the commas between them."""
    return sum(items) + max(len(items) - 1, 0)


def _term_pattern(term: str) -> re.Pattern[str]:
    """The term as a whole phrase, case-sensitive, with any run of spaces between its words."""
    words = r"\s+".join(re.escape(word) for word in term.split())
    return re.compile(rf"(?<!\w){words}(?!\w)")


@dataclass
class _Packer:
    """Builds the views of one `pack` call, caching each passage's serialized size."""

    manager: "ContextManager"
    view: TextView
    terms: Sequence[DefinedTerm]
    neighbors: int
    zones: Mapping[tuple[str, str], str]
    cues: Mapping[str, Sequence[str]]
    _views: dict[str, PassageView] = field(default_factory=dict)
    _sizes: dict[str, int] = field(default_factory=dict)
    _context_sizes: dict[str, int] = field(default_factory=dict)
    _occurrences: dict[str, list[int]] = field(default_factory=dict)
    _term_views: dict[int, TermView] = field(default_factory=dict)
    _patterns: list[re.Pattern[str]] = field(default_factory=list)

    def __post_init__(self) -> None:
        self._patterns = [_term_pattern(term.term) for term in self.terms]

    def passage_view(self, passage: Passage) -> PassageView:
        if passage.id not in self._views:
            lead = self.manager.passages.get(passage.lead_in_id or "")
            fields: dict[str, Any] = {
                "src_id": passage.id,
                "section_path": passage.section_path,
                "text": self.view.text(passage),
                "lead_in": self.view.text(lead) if lead is not None else None,
                # PassageView ignores these four until step 11 adds them, since adding them
                # re-keys every extraction cassette.
                "zone": self.zones.get((passage.doc_id, passage.section_path)),
                "cues": list(self.cues.get(passage.id, ())),
                "small_print": passage.small_print,
                "suspect": passage.suspect,
            }
            self._views[passage.id] = PassageView.model_validate(fields)
        return self._views[passage.id]

    def _size(self, passage: Passage) -> int:
        if passage.id not in self._sizes:
            self._sizes[passage.id] = len(self.passage_view(passage).model_dump_json())
        return self._sizes[passage.id]

    def context_view(self, src_id: str) -> ContextPassageView:
        passage = self.manager.passages[src_id]
        return ContextPassageView(src_id=src_id, text=self.view.text(passage))

    def _context_size(self, src_id: str) -> int:
        if src_id not in self._context_sizes:
            self._context_sizes[src_id] = len(self.context_view(src_id).model_dump_json())
        return self._context_sizes[src_id]

    def term_view(self, index: int) -> TermView:
        if index not in self._term_views:
            term = self.terms[index]
            source = self.manager.passages.get(term.src_id)
            definition = (
                cut(self.view.text(source), DEFINITION_MAX_CHARS)
                if source is not None
                else term.definition
            )
            self._term_views[index] = TermView(term=term.term, definition=definition)
        return self._term_views[index]

    def _terms_of(self, passage: Passage) -> list[int]:
        """The registry terms that occur in one passage, in the order they first occur."""
        if passage.id not in self._occurrences:
            text = self.view.text(passage)
            found = []
            for index, pattern in enumerate(self._patterns):
                match = pattern.search(text)
                if match is not None:
                    found.append((match.start(), -len(match.group(0)), index))
            self._occurrences[passage.id] = [index for _, _, index in sorted(found)]
        return self._occurrences[passage.id]

    def neighbor_ids(self, members: Sequence[Passage]) -> list[str]:
        """Each member's neighbors in its document, never a member, in reading order."""
        inside = {p.id for p in members}
        found: set[str] = set()
        for passage in members:
            found.update(self.manager.around(passage.id, self.neighbors))
        return sorted(found - inside, key=self.manager.order.__getitem__)

    def term_indexes(self, members: Sequence[Passage]) -> list[int]:
        """The first `max_terms` distinct terms of the members, by first occurrence."""
        limit = self.manager.limits.max_terms
        chosen: list[int] = []
        for passage in members:
            for index in self._terms_of(passage):
                if len(chosen) >= limit:
                    return chosen
                if index not in chosen:
                    chosen.append(index)
        return chosen

    def evidence(self, members: Sequence[Passage]) -> int:
        """The estimated tokens of a pack's data: its passages, context and terms."""
        chars = (
            _PACK_KEYS
            + _list_chars([self._size(p) for p in members])
            + _list_chars([self._context_size(s) for s in self.neighbor_ids(members)])
            + _list_chars(
                [len(self.term_view(i).model_dump_json()) for i in self.term_indexes(members)]
            )
        )
        return estimate_tokens(chars, self.manager.limits.chars_per_token)


class ContextManager:
    """Packs the model calls of one run. `passages` is every passage of the run, in reading
    order, so neighbors, lead-ins and term definitions resolve even when only some passages
    are packed. `requirement_sources` maps requirement ids to the passages they quote, for
    `pack_cluster`."""

    def __init__(
        self,
        run_dir: Path,
        limits: ContextLimits,
        passages: Sequence[Passage],
        *,
        requirement_sources: Mapping[str, Sequence[str]] | None = None,
    ) -> None:
        self.run_dir = run_dir
        self.limits = limits
        self.passages = {p.id: p for p in passages}
        if len(self.passages) != len(passages):
            raise ValueError("a passage id appears twice in the run")
        self.order = {p.id: n for n, p in enumerate(passages)}
        self._documents: dict[str, list[str]] = {}
        self._sections: dict[tuple[str, str], list[str]] = {}
        for passage in passages:
            self._documents.setdefault(passage.doc_id, []).append(passage.id)
            self._sections.setdefault((passage.doc_id, passage.section_path), []).append(passage.id)
        self._position = {s: n for ids in self._documents.values() for n, s in enumerate(ids)}
        self.requirement_sources = {k: list(v) for k, v in (requirement_sources or {}).items()}

    def around(self, src_id: str, distance: int) -> list[str]:
        """The passages up to `distance` places before and after one, in its document."""
        ids = self._documents[self.passages[src_id].doc_id]
        at = self._position[src_id]
        return [ids[n] for n in range(max(at - distance, 0), min(at + distance + 1, len(ids)))]

    # --- extract -----------------------------------------------------------------------------

    def pack(
        self,
        node: str,
        passages: Sequence[Passage],
        *,
        view: TextView | None = None,
        fixed_tokens: LayerTokens,
        budget_tokens: int,
        batch_size: int | None,
        neighbors: int,
        terms: Sequence[DefinedTerm] = (),
        zones: Iterable[ZoneRecord] = (),
        cues: Iterable[CueHit] = (),
        first: int = 1,
    ) -> list[ContextPack]:
        """Packs in reading order. `first` numbers the first call, so a coverage round's call
        ids continue the numbering and no manifest file collides."""
        prefix = _prefix(node)
        _check_budget(budget_tokens)
        if batch_size is not None and batch_size < 1:
            raise ValueError("batch_size must be at least 1, or None for a single pack")
        if neighbors < 0:
            raise ValueError("neighbors must not be negative")
        self._check_members([p.id for p in passages])
        packer = _Packer(
            manager=self,
            view=view or IdentityView(self.passages.values()),
            terms=terms,
            neighbors=neighbors,
            zones={(z.doc_id, z.section_path): z.zone for z in zones},
            cues={hit.src_id: list(hit.kinds) for hit in cues},
        )
        room = budget_tokens - _fixed(fixed_tokens)
        groups: list[list[Passage]] = []
        current: list[Passage] = []
        for passage in passages:
            if current and batch_size is not None:
                full = len(current) >= batch_size
                if full or packer.evidence([*current, passage]) > room:
                    groups.append(current)
                    current = []
            current.append(passage)
        if current:
            groups.append(current)
        packs = []
        for number, members in enumerate(groups, start=first):
            call_id = f"{prefix}{number:02d}"
            context_ids = packer.neighbor_ids(members)
            indexes = packer.term_indexes(members)
            manifest = self._manifest(
                node,
                call_id,
                [p.id for p in members],
                context_ids,
                [terms[i].term for i in indexes],
                fixed_tokens,
                packer.evidence(members),
                budget_tokens,
            )
            packs.append(
                ContextPack(
                    call_id=call_id,
                    passages=[packer.passage_view(p) for p in members],
                    context=[packer.context_view(s) for s in context_ids],
                    terms=[packer.term_view(i) for i in indexes],
                    manifest=manifest,
                )
            )
        return packs

    # --- triage --------------------------------------------------------------------------------

    def pack_sections(
        self,
        sections: Sequence[SectionView],
        *,
        fixed_tokens: LayerTokens,
        budget_tokens: int,
        first: int = 1,
    ) -> list[ContextPack]:
        """`triage` calls, `T01` onward. A pack's `included_src_ids` are every passage of its
        sections; its passages, context and terms are empty, since the call reads section
        views. A section larger than the budget goes alone."""
        prefix = _prefix("triage")
        _check_budget(budget_tokens)
        keys = [(s.doc_id, s.section_path) for s in sections]
        if len(set(keys)) != len(keys):
            raise ValueError("a section appears twice in the input")
        unknown = [key for key in keys if key not in self._sections]
        if unknown:
            raise ValueError(f"no passages in sections {unknown}")
        room = budget_tokens - _fixed(fixed_tokens)
        sizes = [len(section.model_dump_json()) for section in sections]
        groups: list[list[int]] = []
        current: list[int] = []
        for index in range(len(sections)):
            if current and self._section_tokens([sizes[i] for i in [*current, index]]) > room:
                groups.append(current)
                current = []
            current.append(index)
        if current:
            groups.append(current)
        packs = []
        for number, members in enumerate(groups, start=first):
            call_id = f"{prefix}{number:02d}"
            included = [src for i in members for src in self._sections[keys[i]]]
            evidence = self._section_tokens([sizes[i] for i in members])
            manifest = self._manifest(
                "triage", call_id, included, [], [], fixed_tokens, evidence, budget_tokens
            )
            packs.append(ContextPack(call_id=call_id, passages=[], manifest=manifest))
        return packs

    def sections_in(self, pack: ContextPack, sections: Sequence[SectionView]) -> list[SectionView]:
        """The sections whose passages one `triage` pack includes, in their input order."""
        keys = {
            (self.passages[s].doc_id, self.passages[s].section_path)
            for s in pack.manifest.included_src_ids
        }
        return [s for s in sections if (s.doc_id, s.section_path) in keys]

    def _section_tokens(self, sizes: Sequence[int]) -> int:
        return estimate_tokens(_SECTION_KEYS + _list_chars(sizes), self.limits.chars_per_token)

    # --- brief ---------------------------------------------------------------------------------

    def pack_brief(
        self,
        sections: Sequence[ZoneRecord],
        requirements: Sequence[Requirement],
        profile: RfpProfile,
        *,
        view: TextView | None = None,
        fixed_tokens: LayerTokens,
        budget_tokens: int,
    ) -> list[ContextPack]:
        """`brief` calls, `F01` onward, from the zone records of every section: the
        `EVALUATION` sections first, then the `INSTRUCTION` sections, each whole and in
        document order. A pack's passages carry their zone, and its manifest names the
        requirements whose passages it holds; a section larger than the budget goes alone."""
        prefix = _prefix("brief")
        _check_budget(budget_tokens)
        chosen = sorted(
            (
                z
                for z in sections
                if z.zone in BRIEF_ZONES and (z.doc_id, z.section_path) in self._sections
            ),
            key=lambda z: (
                BRIEF_ZONES.index(z.zone),
                self.order[self._sections[(z.doc_id, z.section_path)][0]],
            ),
        )
        packer = _Packer(
            manager=self,
            view=view or IdentityView(self.passages.values()),
            terms=(),
            neighbors=0,
            zones={(z.doc_id, z.section_path): z.zone for z in sections},
            cues={},
        )
        members: list[list[str]] = []
        held: list[list[Requirement]] = []
        sizes: list[int] = []
        for zone in chosen:
            ids = self._sections[(zone.doc_id, zone.section_path)]
            inside = set(ids)
            holds = [r for r in requirements if inside & set(r.src_ids)]
            section = BriefSection(
                doc_id=zone.doc_id,
                section_path=zone.section_path,
                passages=[packer.passage_view(self.passages[s]) for s in ids],
            )
            views = [len(requirement_view(r).model_dump_json()) for r in holds]
            sizes.append(len(section.model_dump_json()) + _list_chars(views) + 1)
            members.append(ids)
            held.append(holds)
        fixed = _BRIEF_KEYS + len(profile.model_dump_json())
        room = budget_tokens - _fixed(fixed_tokens)
        groups: list[list[int]] = []
        current: list[int] = []
        for index in range(len(chosen)):
            trial = _list_chars([sizes[i] for i in [*current, index]])
            if current and estimate_tokens(fixed + trial, self.limits.chars_per_token) > room:
                groups.append(current)
                current = []
            current.append(index)
        if current:
            groups.append(current)
        packs = []
        for number, group in enumerate(groups, start=1):
            call_id = f"{prefix}{number:02d}"
            included = [src for i in group for src in members[i]]
            records = list(dict.fromkeys(r.id for i in group for r in held[i]))
            evidence = estimate_tokens(
                fixed + _list_chars([sizes[i] for i in group]), self.limits.chars_per_token
            )
            manifest = self._manifest(
                "brief",
                call_id,
                included,
                [],
                [],
                fixed_tokens,
                evidence,
                budget_tokens,
                records=records,
            )
            views = [packer.passage_view(self.passages[s]) for s in included]
            packs.append(ContextPack(call_id=call_id, passages=views, manifest=manifest))
        return packs

    def brief_sections(self, pack: ContextPack) -> list[BriefSection]:
        """The sections of one `brief` pack, whole, in pack order."""
        found: dict[tuple[str, str], list[PassageView]] = {}
        for view in pack.passages:
            passage = self.passages[view.src_id]
            found.setdefault((passage.doc_id, passage.section_path), []).append(view)
        return [
            BriefSection(doc_id=doc_id, section_path=path, passages=views)
            for (doc_id, path), views in found.items()
        ]

    # --- calls over records ----------------------------------------------------------------------

    def record_manifest(
        self,
        node: str,
        call_id: str,
        record_ids: Sequence[str],
        src_ids: Sequence[str],
        fixed_tokens: LayerTokens,
        evidence_tokens: int,
        budget_tokens: int,
    ) -> ContextManifest:
        """The manifest of one call whose evidence is records or excerpts: `discover`'s, whose
        `record_ids` are the excerpt ids the call was given."""
        _prefix(node)
        _check_budget(budget_tokens)
        return self._manifest(
            node,
            call_id,
            list(src_ids),
            [],
            [],
            fixed_tokens,
            evidence_tokens,
            budget_tokens,
            records=record_ids,
        )

    # --- consolidate -----------------------------------------------------------------------------

    def pack_cluster(
        self, task: ClusterTask, *, fixed_tokens: LayerTokens, budget_tokens: int
    ) -> ContextPack:
        """One `consolidate` call under the group id. `included_src_ids` are the members'
        passages, and `context_src_ids` the context members' passages."""
        _check_budget(budget_tokens)
        included = self._quoted([m.id for m in task.members])
        context = [s for s in self._quoted([m.id for m in task.context]) if s not in included]
        evidence = estimate_tokens(len(task.model_dump_json()), self.limits.chars_per_token)
        needed = _fixed(fixed_tokens) + evidence
        if needed > budget_tokens:
            raise ContextOverflow(
                f"cluster {task.cluster_id} needs about {needed} tokens, over its budget of"
                f" {budget_tokens}"
            )
        manifest = self._manifest(
            "consolidate",
            task.cluster_id,
            included,
            context,
            [],
            fixed_tokens,
            evidence,
            budget_tokens,
        )
        return ContextPack(call_id=task.cluster_id, passages=[], manifest=manifest)

    def _quoted(self, requirement_ids: Sequence[str]) -> list[str]:
        found: list[str] = []
        for requirement_id in requirement_ids:
            try:
                sources = self.requirement_sources[requirement_id]
            except KeyError as exc:
                raise ValueError(f"no passages known for {requirement_id}") from exc
            found += [s for s in sources if s not in found]
        return found

    # --- manifests -------------------------------------------------------------------------------

    def _check_members(self, src_ids: Sequence[str]) -> None:
        if len(set(src_ids)) != len(src_ids):
            raise ValueError("a passage appears twice in the input")
        unknown = [s for s in src_ids if s not in self.passages]
        if unknown:
            raise ValueError(f"passages not in this run: {unknown}")

    def _manifest(
        self,
        node: str,
        call_id: str,
        included: list[str],
        context: list[str],
        terms: list[str],
        fixed_tokens: LayerTokens,
        evidence: int,
        budget_tokens: int,
        *,
        records: Sequence[str] = (),
    ) -> ContextManifest:
        layers = LayerTokens(
            rules=fixed_tokens.rules,
            examples=fixed_tokens.examples,
            evidence=evidence,
            task=fixed_tokens.task,
        )
        manifest = ContextManifest(
            node=node,
            call_id=call_id,
            included_src_ids=included,
            context_src_ids=context,
            terms=terms,
            dropped_src_ids=[],
            included_record_ids=list(records),
            tokens_by_layer=layers,
            budget_tokens=budget_tokens,
            utilization=round((_fixed(layers) + evidence) / budget_tokens, 4),
        )
        folder = self.run_dir / CONTEXT_DIR
        folder.mkdir(parents=True, exist_ok=True)
        (folder / f"{node}-{call_id}.json").write_text(
            manifest.model_dump_json() + "\n", encoding="utf-8", newline="\n"
        )
        return manifest


def requirement_view(requirement: Requirement) -> RequirementView:
    """A verified requirement as a model call sees it."""
    return RequirementView(
        id=requirement.id,
        statement=requirement.statement,
        modality=requirement.modality,
        mandatory=requirement.mandatory,
        hazard=requirement.hazard,
    )


def _prefix(node: str) -> str:
    try:
        return CALL_PREFIX[node]
    except KeyError as exc:
        raise ValueError(f"no call ids for node {node!r}; known: {sorted(CALL_PREFIX)}") from exc


def _check_budget(budget_tokens: int) -> None:
    if budget_tokens < 1:
        raise ValueError("budget_tokens must be at least 1")


__all__ = [
    "BRIEF_ZONES",
    "CALL_PREFIX",
    "ContextManager",
    "ContextOverflow",
    "estimate_tokens",
    "prompt_tokens",
    "requirement_view",
]
