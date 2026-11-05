# Research packs

Recorded domain research for research mode `pack` (ADR-033), one folder per domain, so a run reproduces research with no login. In that mode `discover` selects the pack whose keywords match the brief's topics; `load_pack` refuses a pack whose files changed or went missing, then screens every excerpt and answer before `ask_research` reads them. `bidwright research pack` builds a pack from a finished live run or an existing NotebookLM job, and refuses one that the brief topics of a named run would not select. Two packs are here: `local-government-case-management`, the hero package's domain, built from the DR-18 research job, and `higher-education-procurement`, the development PDF's, built from a live run with a published tender among its sources left out. A run whose topics select neither records "no pack for this domain".

| File | Holds |
|---|---|
| `pack.yaml` | The domain id, title, version, creation date, keywords, topics, the `sha256:` hash of each other file, and the counts |
| `summary.md` | A short summary of the research, for people |
| `sources.jsonl` | One source a line: its `PS-` id, URL, title, host, authority tier from 1 to 4, and the date it was retrieved |
| `excerpts.jsonl` | One excerpt a line: its `PX-` id, its source's id, at most 300 characters of the source's cited text, and whether it is quarantined |
| `domain_brief.json` | The `DomainBrief`: the summary, the domain's patterns, standards and pitfalls, its needs and the open questions, each item citing excerpts |
| `answers.jsonl` | One recorded `ask_research` answer a line: the question, the answer, the excerpts it cites, and whether it is quarantined |

Everything here is external research with the evidence class `EXTERNAL_RESEARCH`: it is never capability evidence, and the summary shows it in an appendix marked unverified. Raw research reports stay out of the repository.
