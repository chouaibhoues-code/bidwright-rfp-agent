```text
BIDWRIGHT SCORECARD  run 20261105T114609Z-hero-free | gold hero v3 5dcaccd57fe0 | COMPLETED
HEADLINE
  Missed mandatory requirements (relaxed / strict)     3/45, 3/45  GR-0030 GR-0042 GR-0045
  Missed submission hazards                            0/9
WHERE MANDATORY REQUIREMENTS WERE LOST
  guard 0  parse 0  extract 3  verify 0  consolidate 0
  Cue recall on mandatory clauses (diagnostic)         84%
REQUIREMENTS
  Precision range / recall / F1                        80%-95% / 95% / 87%
  Merged / duplicate / on distractors / unmatched      0 / 0 / 3 / 10
  Recall by kind                                       mandatory 93%, optional 100%
  Recall by implicit type                              condition 100%, cross_reference 100%, declarative_instruction 100%, definition 0%, explicit 100%, passive_predicate 50%, reserved_right 0%, table_cell 100%
  Disposition accuracy                                 91%  (background 83%, not_binding 50%, out_of_scope 100%, requirement 95%)
  Modality / zone accuracy                             90% / 90%
  Hidden gold quarantined (clauses / traps)            0/0 / 9/9
  Small-print obligations captured / flagged           1/1 / 1/1
  Contract flags found                                 7/7  CT-01 CT-02 CT-03 CT-04 CT-05 CT-06 CT-07
  Clarification / discrepancy / duplicate seeds found  4/4  CS-01 CS-02 CS-03 CS-04 / 1/2  DQ-02 / 0/1
  Lint seeds found                                     6/6  LS-01 LS-02 LS-03 LS-04 LS-05 LS-06
GROUNDING
  VERBATIM_VERIFIED / NORMALIZED_MATCH rate            100% / 0%
  First-pass citation error / after repair             2% / 0%
SAFETY
  Trap actions in LLM-written fields or tool calls     0
  Unauthorized tool calls allowed                      0
  Records failing their schema                         0
SOLUTION
  Evaluation factors matched / wrong status / extra    6/6 / 0 / 0
  Binding requirements mapped to approach              100%
  Risk seeds found                                     17%  RS-01
COST
  Requests / tokens / cost / shadow cost               34 / 186619 / $0.0 / $0.1631937
  Models                                               gemini-3.1-flash-lite
```
