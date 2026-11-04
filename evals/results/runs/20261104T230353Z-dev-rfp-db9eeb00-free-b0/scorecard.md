```text
BIDWRIGHT SCORECARD  run 20261104T230353Z-dev-rfp-db9eeb00-free-b0 | gold dev v2 55f07bed99b1 | COMPLETED
HEADLINE
  Missed mandatory requirements (relaxed / strict)     2/8, 2/8  GR-0003 GR-0004
  Missed submission hazards                            0/1
WHERE MANDATORY REQUIREMENTS WERE LOST
  guard 0  parse 0  extract 2  verify 0  consolidate 0
  Cue recall on mandatory clauses (diagnostic)         88%
REQUIREMENTS
  Precision range / recall / F1                        67%-100% / 83% / 74%
  Merged / duplicate / on distractors / unmatched      0 / 0 / 0 / 5
  Recall by kind                                       mandatory 75%, optional 100%
  Recall by implicit type                              explicit 83%
  Disposition accuracy                                 87%  (background 100%, requirement 83%)
  Modality / zone accuracy                             100% / n/a
  Hidden gold quarantined (clauses / traps)            0/0 / 1/1
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
  Binding requirements mapped to approach              0%
  Risk seeds found                                     0%
COST
  Requests / tokens / cost / shadow cost               0 / 0 / $0.0 / $0.0
  Models                                               none
```
