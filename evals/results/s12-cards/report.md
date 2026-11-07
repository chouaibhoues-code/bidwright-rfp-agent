# S-12: method cards off and on

5 repeats; $0.543031 spent. A family passes by its rule in evals/hypotheses.yaml (`superiority`: its violations fall beyond the off runs' spread).

| Family | Cases | Violations off | Violations on | Result | Detail |
|---|---|---|---|---|---|
| BA | 5 | [0, 0, 0, 0, 0] | [0, 0, 0, 0, 0] | fail | median 0 against 0, spread 0 |
| BEN | 1 | [0, 1, 0, 0, 0] | [1, 2, 0, 0, 0] | fail | median 0 against 0, spread 1 |
| CFG | 1 | [0, 0, 0, 0, 0] | [0, 0, 0, 0, 0] | fail | median 0 against 0, spread 0 |
| DEL | 3 | [0, 0, 0, 0, 0] | [0, 0, 0, 0, 0] | fail | median 0 against 0, spread 0 |
| GOV | 1 | [0, 0, 0, 0, 0] | [0, 0, 0, 0, 0] | fail | median 0 against 0, spread 0 |
| REQ | 5 | [0, 0, 0, 0, 0] | [0, 0, 0, 0, 0] | fail | median 0 against 0, spread 0 |
| RISK | 3 | [0, 0, 0, 0, 0] | [0, 0, 0, 0, 0] | fail | median 0 against 0, spread 0 |

Not run: the node's answer has no field that could show the violation.

- S12-CASE-07 (CFG-002 on `consolidate`): ConsolidationResult holds duplicates, discrepancies, questions and reference links, and no statement of downstream change impact on plan, cost, risks or verification, so no answer can show the violation; the drift check (Iteration 4) implements CFG-002 in code.
