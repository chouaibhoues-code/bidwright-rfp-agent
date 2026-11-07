# Matrix `ex-ladder`

Gold hero v4 c5422494a680. 25 of 25 runs finished and were scored.

## Decisions

| Rung | Control | Metric | Kind | Result | Detail |
|---|---|---|---|---|---|
| ex1 | ex0 | missed_mandatory_count | keep_or_drop | keep | d 35, 90% interval [29, 42]; margin 1, precision_low gain -0.28 (superior, so the secondary does not decide); cost per avoided miss $0.002223 |
| ex2 | ex1 | missed_mandatory_count | keep_or_drop | drop | d -1, 90% interval [-2, 2]; margin 1, precision_low gain -0.0133; cost per avoided miss n/a |
| ex3 | ex1 | missed_mandatory_count | keep_or_drop | drop | d 0, 90% interval [-1, 2]; margin 1, precision_low gain -0.0187; cost per avoided miss n/a |
| ex4 | ex1 | missed_mandatory_count | keep_or_drop | drop | d 0, 90% interval [-1, 2]; margin 1, precision_low gain -0.0187; cost per avoided miss n/a |

## Scores by rung

Median, with the minimum and the maximum in brackets.

| Metric | ex0 | ex1 | ex2 | ex3 | ex4 |
|---|---|---|---|---|---|
| missed_mandatory_count | 36 (30-43) | 1 (1-4) | 2 (2-3) | 1 (1-2) | 1 (1-2) |
| missed_mandatory_strict_count | 36 (30-43) | 1 (1-4) | 2 (2-3) | 1 (1-2) | 1 (1-2) |
| recall | 0.1818 (0.0545-0.2909) | 0.9818 (0.9273-0.9818) | 0.9636 (0.9455-0.9636) | 0.9818 (0.9636-0.9818) | 0.9818 (0.9636-0.9818) |
| precision_low | 1 (1-1) | 0.72 (0.6986-0.7606) | 0.7067 (0.6667-0.7361) | 0.7013 (0.6923-0.7681) | 0.7013 (0.6923-0.7571) |
| precision_high | 1 (1-1) | 0.9863 (0.9733-1) | 1 (1-1) | 1 (0.974-1) | 1 (0.9744-1) |
| f1 | 0.3077 (0.1034-0.4507) | 0.8308 (0.7969-0.8572) | 0.8154 (0.782-0.8346) | 0.8182 (0.812-0.8548) | 0.8182 (0.812-0.848) |
| first_pass_citation_error | 0 (0-0) | 0.0049 (0-0.0066) | 0 (0-0.0108) | 0 (0-0) | 0 (0-0.0138) |
| requests | 3 (3-3) | 8 (7-8) | 7 (7-8) | 8 (8-8) | 13 (13-13) |
| tokens | 64671 (58044-66216) | 84364 (74363-105091) | 89367 (82256-96330) | 91981 (86905-94774) | 155634 (144448-157883) |
| cost_usd | 0 (0-0) | 0 (0-0) | 0 (0-0) | 0 (0-0) | 0 (0-0) |
| shadow_cost_usd | 0.0446465 (0.0326548-0.0495868) | 0.122468 (0.105677-0.155794) | 0.128342 (0.118846-0.153984) | 0.132387 (0.11914-0.137921) | 0.227841 (0.200233-0.234352) |

## Consistency (QS-8)

The median pairwise Jaccard over the gold clause ids each repeat captures.

| Rung | Repeats | Jaccard | Result |
|---|---|---|---|
| ex0 | 5 | 0.3 | warn |
| ex1 | 5 | 1 | pass |
| ex2 | 5 | 0.9811 | pass |
| ex3 | 5 | 0.9815 | pass |
| ex4 | 5 | 0.9815 | pass |
