# Matrix `rk-ladder`

Gold hero v4 c5422494a680. 20 of 20 runs finished and were scored.

## Decisions

| Rung | Control | Metric | Kind | Result | Detail |
|---|---|---|---|---|---|
| rk1-f | rk0 | risk_seed_recall | keep_or_drop | drop | d 0.1667, 90% interval [0, 0.1667]; cost per avoided miss n/a |
| rk1 | rk0 | risk_seed_recall | keep_or_drop | drop | d 0.1667, 90% interval [0, 0.1667]; cost per avoided miss n/a |
| rk1-t | rk1 | risk_seed_recall | keep_or_drop | drop | side rung; d 0, 90% interval [-0.1666, 0.1667]; cost per avoided miss n/a |

## Scores by rung

Median, with the minimum and the maximum in brackets.

| Metric | rk0 | rk1-f | rk1 | rk1-t |
|---|---|---|---|---|
| missed_mandatory_count | 2 (2-2) | 2 (2-2) | 2 (2-2) | 2 (2-2) |
| missed_mandatory_strict_count | 2 (2-2) | 2 (2-2) | 2 (2-2) | 2 (2-2) |
| recall | 0.9636 (0.9636-0.9636) | 0.9636 (0.9636-0.9636) | 0.9636 (0.9636-0.9636) | 0.9636 (0.9636-0.9636) |
| precision_low | 0.7571 (0.7571-0.7571) | 0.7571 (0.7571-0.7571) | 0.7571 (0.7571-0.7571) | 0.7571 (0.7571-0.7571) |
| precision_high | 1 (1-1) | 1 (1-1) | 1 (1-1) | 1 (1-1) |
| f1 | 0.848 (0.848-0.848) | 0.848 (0.848-0.848) | 0.848 (0.848-0.848) | 0.848 (0.848-0.848) |
| first_pass_citation_error | 0 (0-0) | 0 (0-0) | 0 (0-0) | 0 (0-0) |
| requests | 5 (4-5) | 5 (4-5) | 8 (6-8) | 8 (8-8) |
| tokens | 25356 (18312-26363) | 35105 (22252-37750) | 49023 (35729-49470) | 50114 (48929-56275) |
| cost_usd | 0.0128343 (0.010413-0.013931) | 0.0131269 (0.0058067-0.0180144) | 0.0117679 (0-0.0142567) | 0.0137215 (0.0117169-0.0184068) |
| shadow_cost_usd | 0.0204373 (0.0167642-0.0218132) | 0.0218464 (0.0165602-0.0279313) | 0.0229763 (0.02017-0.0237198) | 0.0239516 (0.0216338-0.0291603) |

## Consistency (QS-8)

The median pairwise Jaccard over the gold clause ids each repeat captures.

| Rung | Repeats | Jaccard | Result |
|---|---|---|---|
| rk0 | 5 | 1 | pass |
| rk1-f | 5 | 1 | pass |
| rk1 | 5 | 1 | pass |
| rk1-t | 5 | 1 | pass |
