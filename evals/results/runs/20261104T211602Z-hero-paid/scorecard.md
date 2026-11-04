```text
BIDWRIGHT SCORECARD  run 20261104T211602Z-hero-paid | gold hero v2 9e6f4ecc6ef6 | COMPLETED
HEADLINE
  Missed mandatory requirements (relaxed / strict)     8/45, 8/45  GR-0030 GR-0031 GR-0032 GR-0042 GR-0045 GR-0051 GR-0052 GR-0053
  Missed submission hazards                            0/9
WHERE MANDATORY REQUIREMENTS WERE LOST
  guard 0  parse 0  extract 8  verify 0  consolidate 0
  Cue recall on mandatory clauses (diagnostic)         84%
REQUIREMENTS
  Precision range / recall / F1                        65%-97% / 82% / 72%
  Merged / duplicate / on distractors / unmatched      0 / 1 / 2 / 23
  Recall by kind                                       mandatory 82%, optional 80%
  Recall by implicit type                              condition 100%, cross_reference 100%, declarative_instruction 100%, definition 0%, explicit 89%, passive_predicate 50%, reserved_right 0%, table_cell 0%
  Disposition accuracy                                 82%  (background 100%, not_binding 50%, out_of_scope 100%, requirement 82%)
  Modality / zone accuracy                             98% / 91%
  Hidden gold quarantined (clauses / traps)            0/0 / 9/9
  Small-print obligations captured / flagged           1/1 / 1/1
  Contract flags found                                 7/7  CT-01 CT-02 CT-03 CT-04 CT-05 CT-06 CT-07
  Clarification / discrepancy / duplicate seeds found  4/4  CS-01 CS-02 CS-03 CS-04 / 0/2 / 0/1
  Lint seeds found                                     5/6  LS-01 LS-02 LS-03 LS-04 LS-05
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
  Requests / tokens / cost / shadow cost               25 / 167802 / $0.2339174 / $0.2339174
  Models                                               gemini-3.5-flash-lite
```
