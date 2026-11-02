---
id: extract_oneshot
version: 0.1.0
role: extract
pattern: plain instruction
schema: ExtractResult
examples: clauses
decoding: {gemini: {thinking: minimal}, ollama: {think: false}}
rubric: null
last_tested: null
---
<role>
You list the obligations in a request for proposal (RFP).
</role>

<output_format>
Return JSON that matches the response schema. Give each obligation as an item with the ids of the passages it comes from, an exact quote, a one-sentence statement, its modality, its disposition (BINDING, OPTIONAL, BACKGROUND, NOT_BINDING or OUT_OF_SCOPE), and `hazard`, which is true when missing it could get the bid rejected. List the ids of passages that hold no obligation in `no_obligation_src_ids`.
</output_format>

<examples>
$examples
</examples>

<task>
Based on the whole RFP above, inside the <$data_tag> tags, list every obligation.
</task>

<repair_quotes>
These quotes were not found in their cited passages: $failures. For each item, copy the exact text from the passage, or return it with an empty `quote` to withdraw it.
</repair_quotes>

<repair_missing>
These passage ids are missing from your answer: $missing. Add an item for each, or list it in `no_obligation_src_ids`.
</repair_missing>

<repair_close>
Return only the items you corrected or added, as JSON that matches the response schema.
</repair_close>

<repair_format>
Your answer did not match the response schema: $error. Return the whole result again, as JSON that matches the schema.
</repair_format>

## Why it works

- **It is the control.** EX0, the first rung of the extraction ladder, sends every passage of the RFP in one call with this plain instruction. Each later rung is judged against it.
- **Same examples, same schema, same checks.** The examples, the response schema and the repair messages match `extract.md`, and `verify` checks this rung's quotes too. EX1 therefore measures batching and the prompt contract (rules, decision table, the coverage check), not a change in examples or in quote checking.
- **Deliberately minimal.** No rules beyond the output format, and no decision table. Adding them here would hide what the contract buys.
- **Decoding** matches `extract.md`, so the rungs differ only in what they test.
