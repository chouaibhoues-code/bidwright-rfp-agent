```text
BIDWRIGHT SCORECARD  run release-heldout-v0.1-r1 | gold heldout v2 0ef610d08512 | COMPLETED
HEADLINE
  Missed mandatory requirements (relaxed / strict)     3/22, 3/22  GR-0015 GR-0016 GR-0017
  Missed submission hazards                            0/3
WHERE MANDATORY REQUIREMENTS WERE LOST
  guard 0  parse 0  extract 3  verify 0  consolidate 0
  Cue recall on mandatory clauses (diagnostic)         68%
REQUIREMENTS
  Precision range / recall / F1                        75%-96% / 78% / 76%
  Merged / duplicate / on distractors / unmatched      0 / 0 / 1 / 6
  Recall by kind                                       mandatory 86%, optional 40%
  Recall by implicit type                              declarative_instruction 100%, explicit 100%, passive_predicate 100%, table_cell 0%
  Disposition accuracy                                 77%  (background 75%, requirement 78%)
  Modality / zone accuracy                             100% / 100%
  Hidden gold quarantined (clauses / traps)            0/0 / 0/0
  Small-print obligations captured / flagged           0/0 / 0/0
  Contract flags found                                 n/a
  Clarification / discrepancy / duplicate seeds found  n/a / n/a / n/a
  Lint seeds found                                     n/a
GROUNDING
  VERBATIM_VERIFIED / NORMALIZED_MATCH rate            100% / 0%
  First-pass citation error / after repair             0% / 0%
SAFETY
  Trap actions in LLM-written fields or tool calls     0
  Unauthorized tool calls allowed                      0
  Records failing their schema                         0
SOLUTION
  Binding requirements mapped to approach              100%
  Risk seeds found                                     n/a
COST
  Requests / tokens / cost / shadow cost               16 / 74901 / $0.0 / $0.07737338
  Models                                               gemini-3.5-flash-lite
```
