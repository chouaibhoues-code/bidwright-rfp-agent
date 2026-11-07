# Matrix `so-ladder`

Gold hero v4 c5422494a680. 30 of 30 runs finished and were scored.

## Decisions

| Rung | Control | Metric | Kind | Result | Detail |
|---|---|---|---|---|---|
| so1-f | so0 | gap_assertions | keep_or_drop | drop | d 0, 90% interval [-2, 2]; margin 0, approach_mapping gain 0; cost per avoided miss n/a |
| so1 | so0 | gap_assertions | keep_or_drop | drop | d 0, 90% interval [-2, 2]; margin 0, approach_mapping gain 0; cost per avoided miss n/a |
| so1-t | so1 | gap_assertions | keep_or_drop | drop | side rung; d 0, 90% interval [-2, 2]; margin 0, approach_mapping gain 0; cost per avoided miss n/a |
| so2 | so0 | gap_assertions | keep_or_drop | drop | d 0, 90% interval [-2, 2]; margin 0, approach_mapping gain 0; cost per avoided miss n/a |
| so3 | so0 | gap_assertions | keep_or_drop | keep | d 3, 90% interval [1, 3]; margin 0, approach_mapping gain -0.3559 (superior, so the secondary does not decide); cost per avoided miss n/a |

## Scores by rung

Median, with the minimum and the maximum in brackets.

| Metric | so0 | so1-f | so1 | so1-t | so2 | so3 |
|---|---|---|---|---|---|---|
| missed_mandatory_count | 2 (2-2) | 2 (2-2) | 2 (2-2) | 2 (2-2) | 2 (2-2) | 2 (2-2) |
| missed_mandatory_strict_count | 2 (2-2) | 2 (2-2) | 2 (2-2) | 2 (2-2) | 2 (2-2) | 2 (2-2) |
| recall | 0.9636 (0.9636-0.9636) | 0.9636 (0.9636-0.9636) | 0.9636 (0.9636-0.9636) | 0.9636 (0.9636-0.9636) | 0.9636 (0.9636-0.9636) | 0.9636 (0.9636-0.9636) |
| precision_low | 0.7571 (0.7571-0.7571) | 0.7571 (0.7571-0.7571) | 0.7571 (0.7571-0.7571) | 0.7571 (0.7571-0.7571) | 0.7571 (0.7571-0.7571) | 0.7571 (0.7571-0.7571) |
| precision_high | 1 (1-1) | 1 (1-1) | 1 (1-1) | 1 (1-1) | 1 (1-1) | 1 (1-1) |
| f1 | 0.848 (0.848-0.848) | 0.848 (0.848-0.848) | 0.848 (0.848-0.848) | 0.848 (0.848-0.848) | 0.848 (0.848-0.848) | 0.848 (0.848-0.848) |
| first_pass_citation_error | 0 (0-0) | 0 (0-0) | 0 (0-0) | 0 (0-0) | 0 (0-0) | 0 (0-0) |
| requests | 8 (8-10) | 27 (27-29) | 75 (70-76) | 96 (92-97) | 90 (85-94) | 90 (88-96) |
| tokens | 60187 (55881-70248) | 103044 (99309-113485) | 223319 (209627-230480) | 302295 (288209-311423) | 265267 (244591-276826) | 271504 (265395-299357) |
| cost_usd | 0 (0-0) | 0 (0-0) | 0.017285 (0-0.0620355) | 0.112428 (0.107432-0.117393) | 0.0197352 (0.0128118-0.0222316) | 0.0623685 (0.0493506-0.0653366) |
| shadow_cost_usd | 0.0480872 (0.044089-0.0521727) | 0.0685264 (0.0649477-0.072604) | 0.109181 (0.103441-0.112536) | 0.145381 (0.137914-0.151898) | 0.124067 (0.122768-0.129641) | 0.140427 (0.130226-0.151729) |

## Consistency (QS-8)

The median pairwise Jaccard over the gold clause ids each repeat captures.

| Rung | Repeats | Jaccard | Result |
|---|---|---|---|
| so0 | 5 | 1 | pass |
| so1-f | 5 | 1 | pass |
| so1 | 5 | 1 | pass |
| so1-t | 5 | 1 | pass |
| so2 | 5 | 1 | pass |
| so3 | 5 | 1 | pass |
