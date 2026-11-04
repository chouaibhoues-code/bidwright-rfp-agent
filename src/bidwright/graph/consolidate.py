"""`consolidate`: requirement groups, discrepancies and clarification questions (Iteration 1,
step 14; ADR-019).

`clusters.py` forms the clusters in code. Each cluster of two or more members, or of one member
that gained context or a link, becomes a `ClusterTask` packed through
`ContextManager.pack_cluster`, and one call of `consolidate@0.1.0` through
`RunContext.structured` (one call, one format repair) returns a `ConsolidationResult`. Code then
settles it: ids that are neither members nor context are dropped, so are duplicate pairs
outside the members, discrepancies naming fewer than 2 ids and questions without a question
mark; a discrepancy between requirements in different zones is `conditional` whatever the model
said; and every question-severity lint finding no returned question cites gets a question from
its template, with origin `lint_template`.

A one-member cluster with no link and no context becomes a group in code, titled by its
section, and so does a cluster whose call fails after the repair, which ends the run
`DEGRADED` with "consolidate: N clusters fell back to code groups". `DS-` and `CQ-` ids run
across groups in group order, then in output order; a question's `src_ids` are its
requirements' passages. No path removes a requirement: every member is in exactly one group.
Writes `requirement_groups.jsonl`, `discrepancies.jsonl` and `questions.jsonl`.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path

from bidwright.clusters import Cluster, build_clusters, precedence_passages
from bidwright.config import Config
from bidwright.graph.nodes import RunContext
from bidwright.harness.context import ContextManager, prompt_tokens
from bidwright.harness.view import IdentityView, TextView
from bidwright.schemas import (
    ClarificationQuestion,
    ClusterLintView,
    ClusterMember,
    ClusterTask,
    ConsolidationResult,
    ContextPassageView,
    ControlRegister,
    Discrepancy,
    DiscrepancyProposal,
    DuplicatePair,
    LintFinding,
    Passage,
    PrecedenceEntry,
    ReferenceLink,
    Requirement,
    RequirementGroup,
)

NODE = "consolidate"


@dataclass
class QuestionDraft:
    text: str
    requirement_ids: list[str]
    lint_finding_ids: list[str]
    origin: str  # "consolidate" or "lint_template"


@dataclass
class GroupDraft:
    """One cluster's settled result, before ids run across groups."""

    cluster: Cluster
    topic: str
    llm: bool
    duplicates: list[DuplicatePair] = field(default_factory=list)
    references: list[ReferenceLink] = field(default_factory=list)
    discrepancies: list[DiscrepancyProposal] = field(default_factory=list)
    questions: list[QuestionDraft] = field(default_factory=list)
    fell_back: bool = False


@dataclass
class ConsolidateOutcome:
    groups: list[RequirementGroup]
    discrepancies: list[Discrepancy]
    questions: list[ClarificationQuestion]
    degraded: str | None


# --- the cluster task -------------------------------------------------------------------------


def _view_quote(requirement: Requirement, passages: Mapping[str, Passage], view: TextView) -> str:
    """The view's text over the requirement's span, so the model sees what the view shows."""
    passage = passages[requirement.src_ids[0]]
    if requirement.quote_span is None:
        return requirement.quote
    start, end = (offset - passage.start for offset in requirement.quote_span)
    shown = view.text(passage)
    return shown[start:end] if 0 <= start < end <= len(shown) else requirement.quote


def _member(
    requirement: Requirement, passages: Mapping[str, Passage], view: TextView
) -> ClusterMember:
    first = passages[requirement.src_ids[0]]
    return ClusterMember(
        id=requirement.id,
        statement=requirement.statement,
        modality=requirement.modality,
        disposition=requirement.disposition,
        quote=_view_quote(requirement, passages, view),
        doc_id=first.doc_id,
        section_path=first.section_path,
    )


def _lint_view(
    finding: LintFinding, requirement: Requirement, passages: Mapping[str, Passage], view: TextView
) -> ClusterLintView:
    """The finding's match as the view shows it, at the same place in the quote."""
    shown = _view_quote(requirement, passages, view)
    at = requirement.quote.find(finding.match)
    match = shown[at : at + len(finding.match)] if at >= 0 else finding.match
    return ClusterLintView(
        id=finding.id, kind=finding.kind, requirement_id=finding.requirement_id, match=match
    )


def cluster_task(
    cluster: Cluster,
    requirements: Mapping[str, Requirement],
    passages: Mapping[str, Passage],
    *,
    register: ControlRegister | None = None,
    lint: Sequence[LintFinding] = (),
    precedence: Sequence[Passage] = (),
    view: TextView | None = None,
) -> ClusterTask:
    shown = view or IdentityView(passages.values())
    members = set(cluster.members)
    return ClusterTask(
        cluster_id=cluster.group_id,
        members=[_member(requirements[r], passages, shown) for r in cluster.members],
        context=[_member(requirements[r], passages, shown) for r in cluster.context],
        precedence=[
            PrecedenceEntry(doc_id=e.doc_id, role=e.role, precedence=e.precedence)
            for e in (register.documents if register else [])
        ],
        precedence_clause=[
            ContextPassageView(src_id=p.id, text=shown.text(p))
            for p in (precedence if cluster.addendum else [])
        ],
        lint=[
            _lint_view(f, requirements[f.requirement_id], passages, shown)
            for f in lint
            if f.requirement_id in members
        ],
    )


# --- settling one answer ----------------------------------------------------------------------


def _template(finding: LintFinding, config: Config) -> str | None:
    templates = {rule.id: rule.question for rule in config.lint.rules}
    templates |= {name: check.question for name, check in config.lint.checks.items()}
    template = templates.get(finding.rule)
    if not template:
        return None
    text = template.format(match=finding.match, requirement_id=finding.requirement_id)
    return text if text.rstrip().endswith("?") else f"{text.rstrip()}?"


def template_questions(
    findings: Sequence[LintFinding], answered: set[str], config: Config
) -> list[QuestionDraft]:
    """One question per question-severity finding that no returned question cites."""
    drafts = []
    for finding in findings:
        if finding.severity != "question" or finding.id in answered:
            continue
        text = _template(finding, config)
        if text:
            drafts.append(
                QuestionDraft(text, [finding.requirement_id], [finding.id], "lint_template")
            )
    return drafts


def _section_title(
    cluster: Cluster, requirements: Mapping[str, Requirement], passages: Mapping[str, Passage]
) -> str:
    first = passages[requirements[cluster.members[0]].src_ids[0]]
    return first.section_path.split(" > ")[-1] or first.doc_id


def code_group(
    cluster: Cluster,
    requirements: Mapping[str, Requirement],
    passages: Mapping[str, Passage],
    findings: Sequence[LintFinding],
    config: Config,
    *,
    fell_back: bool = False,
) -> GroupDraft:
    """A group made in code: titled by its section, with template questions only."""
    members = set(cluster.members)
    own = [f for f in findings if f.requirement_id in members]
    return GroupDraft(
        cluster=cluster,
        topic=_section_title(cluster, requirements, passages),
        llm=False,
        questions=template_questions(own, set(), config),
        fell_back=fell_back,
    )


def settle(
    cluster: Cluster,
    result: ConsolidationResult,
    requirements: Mapping[str, Requirement],
    findings: Sequence[LintFinding],
    config: Config,
) -> GroupDraft:
    """Keep what the cluster can carry, and add template questions for unanswered findings."""
    members = list(cluster.members)
    allowed = set(members) | set(cluster.context)
    own = [f for f in findings if f.requirement_id in set(members)]
    own_ids = {f.id for f in own}
    duplicates = [
        d
        for d in result.duplicates
        if d.requirement_id in members
        and d.duplicate_of in members
        and d.requirement_id != d.duplicate_of
    ]
    references = [
        ref.model_copy(update={"resolved_ids": [i for i in ref.resolved_ids if i in allowed]})
        for ref in result.references
        if ref.requirement_id in allowed
    ]
    discrepancies = []
    for proposal in result.discrepancies:
        ids = [i for i in dict.fromkeys(proposal.requirement_ids) if i in allowed]
        if len(ids) < 2:
            continue
        zones = {requirements[i].zone for i in ids}
        state = "conditional" if len(zones) > 1 else proposal.state
        discrepancies.append(proposal.model_copy(update={"requirement_ids": ids, "state": state}))
    questions = []
    answered: set[str] = set()
    for proposal in result.questions:
        if not proposal.text.rstrip().endswith("?"):
            continue
        lint_ids = [i for i in proposal.lint_finding_ids if i in own_ids]
        answered.update(lint_ids)
        ids = [i for i in dict.fromkeys(proposal.requirement_ids) if i in allowed]
        questions.append(QuestionDraft(proposal.text, ids, lint_ids, "consolidate"))
    questions += template_questions(own, answered, config)
    return GroupDraft(
        cluster=cluster,
        topic=result.topic,
        llm=True,
        duplicates=duplicates,
        references=references,
        discrepancies=discrepancies,
        questions=questions,
    )


def consolidate_cluster(
    ctx: RunContext,
    task: ClusterTask,
    cluster: Cluster,
    manager: ContextManager,
    requirements: Mapping[str, Requirement],
    passages: Mapping[str, Passage],
    findings: Sequence[LintFinding],
    config: Config,
) -> GroupDraft:
    """One model call for one cluster, or a code group when it fails after the repair."""
    prompt = ctx.prompts[NODE]
    manager.pack_cluster(
        task,
        fixed_tokens=prompt_tokens(prompt, config.limits.context.chars_per_token),
        budget_tokens=config.limits.context.budgets[NODE],
    )
    rendered = prompt.render(task.model_dump_json(), run_id=ctx.run_id, cluster_id=task.cluster_id)
    result, _ = ctx.structured(
        prompt, rendered.messages, ConsolidationResult, node=NODE, input_hash=rendered.input_hash
    )
    if not isinstance(result, ConsolidationResult):
        return code_group(cluster, requirements, passages, findings, config, fell_back=True)
    return settle(cluster, result, requirements, findings, config)


# --- assembly ---------------------------------------------------------------------------------


def assemble(
    drafts: Sequence[GroupDraft], requirements: Mapping[str, Requirement]
) -> ConsolidateOutcome:
    """Number discrepancies and questions across groups in group order, then output order."""
    groups, discrepancies, questions = [], [], []
    for draft in sorted(drafts, key=lambda d: d.cluster.group_id):
        group_id = draft.cluster.group_id
        discrepancy_ids, question_ids = [], []
        for proposal in draft.discrepancies:
            discrepancy = Discrepancy(
                id=f"DS-{len(discrepancies) + 1:03d}",
                group_id=group_id,
                requirement_ids=proposal.requirement_ids,
                kind=proposal.kind,
                state=proposal.state,
                description=proposal.description,
                resolved_by=proposal.resolved_by,
            )
            discrepancies.append(discrepancy)
            discrepancy_ids.append(discrepancy.id)
        for question in draft.questions:
            sources = [s for i in question.requirement_ids for s in requirements[i].src_ids]
            clarification = ClarificationQuestion.model_validate(
                {
                    "id": f"CQ-{len(questions) + 1:03d}",
                    "group_id": group_id,
                    "text": question.text,
                    "requirement_ids": question.requirement_ids,
                    "src_ids": list(dict.fromkeys(sources)),
                    "lint_finding_ids": question.lint_finding_ids,
                    "origin": question.origin,
                }
            )
            questions.append(clarification)
            question_ids.append(clarification.id)
        groups.append(
            RequirementGroup(
                id=group_id,
                member_ids=draft.cluster.members,
                context_ids=draft.cluster.context,
                topic=draft.topic,
                duplicates=draft.duplicates,
                references=draft.references,
                discrepancy_ids=discrepancy_ids,
                question_ids=question_ids,
                llm=draft.llm,
            )
        )
    fell_back = sum(1 for d in drafts if d.fell_back)
    degraded = f"consolidate: {fell_back} clusters fell back to code groups" if fell_back else None
    return ConsolidateOutcome(groups, discrepancies, questions, degraded)


def write_consolidation(run_dir: Path, outcome: ConsolidateOutcome) -> None:
    """The three files; `consolidate` is their only writer."""
    run_dir.mkdir(parents=True, exist_ok=True)
    for name, rows in (
        ("requirement_groups.jsonl", outcome.groups),
        ("discrepancies.jsonl", outcome.discrepancies),
        ("questions.jsonl", outcome.questions),
    ):
        body = "".join(row.model_dump_json() + "\n" for row in rows)
        (run_dir / name).write_text(body, encoding="utf-8", newline="\n")


def consolidate(
    ctx: RunContext,
    requirements: Sequence[Requirement],
    passages: Sequence[Passage],
    config: Config,
    run_dir: Path,
    *,
    register: ControlRegister | None = None,
    findings: Sequence[LintFinding] = (),
    view: TextView | None = None,
) -> ConsolidateOutcome:
    """Cluster, ask the model about each cluster that needs it, settle, and write the files.
    The graph runs the model step as one `Send` per cluster from step 16; this runs them in
    order, for tests and for any caller without the graph."""
    by_id = {r.id: r for r in requirements}
    by_passage = {p.id: p for p in passages}
    clusters = build_clusters(requirements, by_passage, register, config.limits.clusters)
    precedence = precedence_passages(passages)
    manager = ContextManager(
        run_dir,
        config.limits.context,
        passages,
        requirement_sources={r.id: r.src_ids for r in requirements},
    )
    drafts = []
    for cluster in clusters:
        if not cluster.to_model:
            drafts.append(code_group(cluster, by_id, by_passage, findings, config))
            continue
        task = cluster_task(
            cluster,
            by_id,
            by_passage,
            register=register,
            lint=findings,
            precedence=precedence,
            view=view,
        )
        drafts.append(
            consolidate_cluster(ctx, task, cluster, manager, by_id, by_passage, findings, config)
        )
    outcome = assemble(drafts, by_id)
    write_consolidation(run_dir, outcome)
    return outcome


__all__ = [
    "ConsolidateOutcome",
    "GroupDraft",
    "assemble",
    "cluster_task",
    "code_group",
    "consolidate",
    "consolidate_cluster",
    "settle",
    "template_questions",
    "write_consolidation",
]
