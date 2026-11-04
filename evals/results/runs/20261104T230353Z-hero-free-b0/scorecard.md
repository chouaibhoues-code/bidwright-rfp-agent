```text
BIDWRIGHT SCORECARD  run 20261104T230353Z-hero-free-b0 | gold hero v2 9e6f4ecc6ef6 | COMPLETED
HEADLINE
  Missed mandatory requirements (relaxed / strict)     10/45, 10/45  GR-0004 GR-0009 GR-0018 GR-0030 GR-0031 GR-0032 GR-0038 GR-0039 GR-0042 GR-0045
  Missed submission hazards                            1/9
WHERE MANDATORY REQUIREMENTS WERE LOST
  guard 0  parse 0  extract 10  verify 0  consolidate 0
  Cue recall on mandatory clauses (diagnostic)         84%
REQUIREMENTS
  Precision range / recall / F1                        76%-90% / 82% / 79%
  Merged / duplicate / on distractors / unmatched      0 / 0 / 6 / 8
  Recall by kind                                       mandatory 78%, optional 100%
  Recall by implicit type                              condition 0%, cross_reference 0%, declarative_instruction 0%, definition 0%, explicit 96%, passive_predicate 50%, reserved_right 0%, table_cell 0%
  Disposition accuracy                                 73%  (background 83%, not_binding 0%, out_of_scope 0%, requirement 78%)
  Modality / zone accuracy                             100% / n/a
  Hidden gold quarantined (clauses / traps)            0/0 / 9/9
  Small-print obligations captured / flagged           1/1 / 1/1
  Contract flags found                                 0/7
  Clarification / discrepancy / duplicate seeds found  0/4 / 0/2 / 0/1
  Lint seeds found                                     0/6
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
