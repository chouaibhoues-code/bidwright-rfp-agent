```text
BIDWRIGHT SCORECARD  run 20261113T042518Z-dev-rfp-db9eeb00-free | gold dev v3 f00d5c7bda57 | COMPLETED
HEADLINE
  Missed mandatory requirements (relaxed / strict)     0/8, 0/8
  Missed submission hazards                            0/1
WHERE MANDATORY REQUIREMENTS WERE LOST
  guard 0  parse 0  extract 0  verify 0  consolidate 0
  Cue recall on mandatory clauses (diagnostic)         88%
REQUIREMENTS
  Precision range / recall / F1                        100%-100% / 100% / 100%
  Merged / duplicate / on distractors / unmatched      0 / 0 / 0 / 0
  Recall by kind                                       mandatory 100%, optional 100%
  Recall by implicit type                              explicit 100%
  Disposition accuracy                                 100%  (background 100%, requirement 100%)
  Modality / zone accuracy                             100% / 100%
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
  Evaluation factors matched / wrong status / extra    4/4 / 0 / 0
  Binding requirements mapped to approach              88%
  Risk seeds found                                     0%
  Seeded gaps claimed (QS-5) / gap assertions          no gap seeds
  UNVERIFIED precision / recall / joint error          no gap seeds
  Decision accuracy / distinct decisions               no decision seeds / 2
  Manifest checks failed / untraced packages / gaps    2/9 / 0 / 1
  Technology seeds right / wrong / not judged          no tech seeds
  Risks complete / generic risks rejected              100% / 0
  Options reproduced                                   yes
COST
  Requests / tokens / cost / shadow cost               32 / 99027 / $0.0 / $0.0838505
  Models                                               gemini-3.5-flash-lite, gpt-oss-120b
```
