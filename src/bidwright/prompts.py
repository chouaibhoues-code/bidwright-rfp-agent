"""Versioned prompts: front-matter, `string.Template.substitute` rendering, seeded delimiters.

A prompt file in `prompts/` is Markdown with YAML front-matter. Its body is the system
instruction in XML-style tags, plus a `<task>` element, which goes last in the user message,
after the data. Follow-up messages are elements too: `<final_task>` closes an agent loop, and
`<repair_...>` elements ask for one targeted repair. Everything from the `## Why it works`
heading on is notes for people and never reaches a model.

`substitute` raises on a missing value and never re-reads what it inserts, so quotes with
braces or `$` stay exact. Data is never substituted into a template: it goes between
delimiter tags seeded from the run id, so the same run always gets the same tags.
"""

import hashlib
import json
import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from string import Template
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator

from bidwright import schemas
from bidwright.config import Provider, Thinking
from bidwright.llm.schema import sha256_of
from bidwright.llm.types import Message

PROMPTS_DIR = Path(__file__).resolve().parents[2] / "prompts"
EXAMPLES_FILE = Path("examples") / "mini_rfp.yaml"
NOTES_HEADING = "## Why it works"
_TASK_ELEMENT = re.compile(r"\s*<(task|final_task|repair_[a-z_]+)>\s*(.*?)\s*</\1>", re.DOTALL)
_FRONT_MATTER = re.compile(r"\A---\n(.*?)\n---\n(.*)\Z", re.DOTALL)

Value = str | int


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Decoding(_Strict):
    """What a prompt may set per provider. Model and provider stay in config/models.yaml."""

    thinking: Thinking | None = None
    think: bool | None = None
    num_ctx: int | None = Field(default=None, gt=0)


class FrontMatter(_Strict):
    id: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    version: str = Field(pattern=r"^\d+\.\d+\.\d+$")
    role: Literal["extract", "reason", "assess", "critic", "judge"]
    pattern: str
    output_schema: str = Field(alias="schema")
    examples: str | None = None
    decoding: dict[Provider, Decoding] = Field(default_factory=dict)
    rubric: str | None = None
    last_tested: date | None = None

    @field_validator("output_schema")
    @classmethod
    def _is_model_facing(cls, name: str) -> str:
        model = getattr(schemas, name, None)
        if not (isinstance(model, type) and issubclass(model, schemas.Facing)):
            raise ValueError(f"{name!r} is not a model-facing schema in bidwright.schemas")
        return name


@dataclass(frozen=True)
class Rendered:
    """One call's messages, with the two hashes its cassette key needs."""

    messages: tuple[Message, ...]
    prompt_hash: str
    input_hash: str
    tag: str


@dataclass(frozen=True)
class Prompt:
    meta: FrontMatter
    system: str
    tasks: dict[str, Template]
    notes: str
    path: Path
    examples: str = ""  # the rendered examples, already inside `system`, kept for token counts

    @property
    def ref(self) -> str:
        return f"{self.meta.id}@{self.meta.version}"

    @property
    def schema(self) -> type[schemas.Facing]:
        return getattr(schemas, self.meta.output_schema)

    @property
    def decoding(self) -> dict[str, dict[str, object]]:
        """The front-matter decoding block, in the form `LLMClient.complete` takes."""
        return {p: d.model_dump(exclude_none=True) for p, d in self.meta.decoding.items()}

    @property
    def hash(self) -> str:
        """Covers everything a model sees from this file, and nothing from the notes."""
        tasks = {name: template.template for name, template in sorted(self.tasks.items())}
        return sha256_of(
            {"ref": self.ref, "system": self.system, "tasks": tasks, "decoding": self.decoding}
        )

    def task_text(self, name: str = "task", **values: Value) -> str:
        if name not in self.tasks:
            raise KeyError(f"{self.ref} has no <{name}> element")
        return self.tasks[name].substitute(values)

    def render(self, data: str, *, run_id: str, task: str = "task", **values: Value) -> Rendered:
        """System instruction first, then the data inside its tags, then the task."""
        tag = delimiter_tag(run_id, data)
        instruction = self.task_text(task, data_tag=tag, **values)
        user = f"<{tag}>\n{data}\n</{tag}>\n\n{instruction}"
        return Rendered(
            messages=(Message("system", self.system), Message("user", user)),
            prompt_hash=self.hash,
            input_hash=sha256_of({"data": data, "task": task, "values": values}),
            tag=tag,
        )


def delimiter_tag(run_id: str, data: str = "") -> str:
    """`data-` and 8 hex digits seeded from the run id.

    A candidate tag that already occurs in the data is skipped, deterministically, so the data
    can never close its own tag. Delimiters are hygiene, not a security boundary.
    """
    if not run_id:
        raise ValueError("a run id is needed to seed the delimiters")
    for attempt in range(1000):
        seed = run_id if attempt == 0 else f"{run_id}#{attempt}"
        tag = "data-" + hashlib.sha256(seed.encode("utf-8")).hexdigest()[:8]
        if tag not in data:
            return tag
    raise ValueError("every candidate delimiter tag occurs in the data")


def load_prompt(prompt_id: str, root: Path = PROMPTS_DIR) -> Prompt:
    path = root / f"{prompt_id}.md"
    match = _FRONT_MATTER.match(path.read_text(encoding="utf-8"))
    if match is None:
        raise ValueError(f"{path}: the front-matter must open and close with ---")
    meta = FrontMatter.model_validate(yaml.safe_load(match.group(1)))
    if meta.id != prompt_id:
        raise ValueError(f"{path}: front-matter id {meta.id!r} differs from the file name")
    body, _, notes = match.group(2).partition(NOTES_HEADING)
    tasks: dict[str, Template] = {}
    for name, text in _TASK_ELEMENT.findall(body):
        if name in tasks:
            raise ValueError(f"{path}: more than one <{name}> element")
        tasks[name] = _template(text, path)
    body = _TASK_ELEMENT.sub("", body)
    if "task" not in tasks:
        raise ValueError(f"{path}: no <task> element")
    system = _template(body.strip(), path)
    placeholders = set(system.get_identifiers())
    if placeholders != ({"examples"} if meta.examples else set()):
        raise ValueError(f"{path}: the system part may use only $examples, and only with examples")
    examples = render_examples(meta.examples, root) if meta.examples else ""
    return Prompt(
        meta=meta,
        system=system.substitute(examples=examples),
        tasks=tasks,
        notes=notes.strip(),
        path=path,
        examples=examples,
    )


def load_prompt_ref(ref: str, root: Path = PROMPTS_DIR) -> Prompt:
    """Load `id@version`, as `config/agents.yaml` names prompts, and check the version."""
    prompt_id, _, version = ref.partition("@")
    prompt = load_prompt(prompt_id, root)
    if prompt.meta.version != version:
        raise ValueError(f"{ref}: the file is at version {prompt.meta.version}")
    return prompt


def _template(text: str, path: Path) -> Template:
    template = Template(text)
    if not template.is_valid():
        raise ValueError(f"{path}: a stray $ in the prompt; write $$ for a literal dollar sign")
    return template


# --- Few-shot examples, rendered from prompts/examples/mini_rfp.yaml ---------------------


def render_examples(name: str, root: Path = PROMPTS_DIR) -> str:
    sets = yaml.safe_load((root / EXAMPLES_FILE).read_text(encoding="utf-8"))
    renderers: dict[str, Callable[[Any], str]] = {
        "clauses": _clause_examples,
        "approach": _approach_examples,
        "risk": _risk_examples,
        "draft": _draft_examples,
        "triage": _triage_examples,
    }
    if name not in renderers or name not in sets:
        raise ValueError(f"no example set {name!r} in {EXAMPLES_FILE}")
    return renderers[name](sets[name])


def _dump(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False)


def _json_list(prefix: str, key: str, rows: list[Any], suffix: str = "}") -> str:
    lines = ",\n".join(f" {_dump(row)}" for row in rows)
    return f'{prefix}"{key}": [\n{lines}\n]{suffix}'


def _clause_examples(clauses: list[dict[str, Any]]) -> str:
    passages, items, none = [], [], []
    for clause in clauses:
        passages.append(
            {
                "src_id": clause["src_id"],
                "section_path": clause["section_path"],
                "text": clause["text"],
                "lead_in": clause.get("lead_in"),
            }
        )
        expect = clause.get("expect")
        if expect is None:
            none.append(clause["src_id"])
            continue
        if expect["quote"] not in clause["text"]:
            raise ValueError(f"example {clause['src_id']}: the quote is not in the passage")
        items.append({"src_ids": [clause["src_id"]], **expect})
    batch = {"batch_id": "EXAMPLE", "passages": passages}
    result = {"items": items, "no_obligation_src_ids": none}
    schemas.ExtractBatch.model_validate(batch)
    schemas.ExtractResult.model_validate(result)
    return "\n".join(
        [
            "A batch:",
            _json_list('{"batch_id": "EXAMPLE", ', "passages", passages),
            "Its result:",
            _json_list("{", "items", items, f', "no_obligation_src_ids": {_dump(none)}}}'),
        ]
    )


def _approach_examples(example: dict[str, Any]) -> str:
    schemas.ApproachInput.model_validate(example["input"])
    schemas.ApproachResult.model_validate(example["output"])
    output = example["output"]
    return "\n".join(
        [
            "Requirements:",
            _json_list("{", "requirements", example["input"]["requirements"]),
            "An approach:",
            _json_list(
                "{",
                "items",
                output["items"],
                f', "unmapped_requirement_ids": {_dump(output["unmapped_requirement_ids"])},'
                f' "open_questions": {_dump(output["open_questions"])}}}',
            ),
        ]
    )


def _risk_examples(example: dict[str, Any]) -> str:
    schemas.RiskRegister.model_validate(example["register"])
    schemas.RiskProposal.model_validate(example["generic"]["risk"])
    register = example["register"]
    return "\n".join(
        [
            "Passages found with search_rfp:",
            "\n".join(f" {_dump(passage)}" for passage in example["evidence"]),
            "A final register built on them:",
            _json_list(
                "{",
                "risks",
                register["risks"],
                f', "open_questions": {_dump(register["open_questions"])}}}',
            ),
            "Not acceptable, because " + example["generic"]["why"] + ":",
            f" {_dump(example['generic']['risk'])}",
        ]
    )


def _draft_examples(examples: list[dict[str, Any]]) -> str:
    blocks = []
    for example in examples:
        schemas.DraftTask.model_validate(example["task"])
        schemas.DraftResult.model_validate(example["result"])
        blocks.append(
            "\n".join(
                [
                    f"Section {example['task']['section_id']}, from these records:",
                    "\n".join(f" {_dump(record)}" for record in example["task"]["records"]),
                    "Its draft:",
                    f" {_dump(example['result'])}",
                ]
            )
        )
    return "\n\n".join(blocks)


def _triage_examples(example: dict[str, Any]) -> str:
    """One outline and its result. Every zone entry names an outline section, and every
    hazard cites an id the outline shows in square brackets."""
    outline = schemas.TriageInput.model_validate(example["input"])
    result = schemas.TriageResult.model_validate(example["output"])
    sections = {(s.doc_id, s.section_path) for s in outline.sections}
    if {(z.doc_id, z.section_path) for z in result.zones} != sections:
        raise ValueError("the triage example must give every section exactly one zone")
    shown = " ".join(s.first_text for s in outline.sections)
    for hazard in result.hazards:
        missing = [i for i in hazard.src_ids if f"[{i}]" not in shown]
        if missing:
            raise ValueError(
                f"triage example hazard cites ids the outline does not show: {missing}"
            )
    output = example["output"]
    profile = f', "profile": {_dump(output["profile"])}'
    return "\n".join(
        [
            "An outline:",
            _json_list("{", "sections", example["input"]["sections"]),
            "Its result:",
            _json_list("{", "zones", output["zones"], profile)
            + _json_list(", ", "hazards", output["hazards"]),
        ]
    )
