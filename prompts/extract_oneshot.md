---
id: extract_oneshot
version: 0.4.0
role: extract
pattern: plain instruction
schema: ExtractResult
examples: null
decoding: {gemini: {thinking: medium}, ollama: {think: false}}
rubric: null
last_tested: null
---
<role>
You list the obligations in a request for proposal (RFP).
</role>

<output_format>
Return JSON that matches the response schema. Give each obligation as an item with the ids of the passages it comes from, an exact quote, a one-sentence statement, its modality, its disposition (BINDING, OPTIONAL, BACKGROUND, NOT_BINDING or OUT_OF_SCOPE), and `hazard`, which is true when missing it could get the bid rejected. List the ids of passages that hold no obligation in `no_obligation_src_ids`.
</output_format>

<task>
Based on the whole RFP above, inside the <$data_tag> tags, list every obligation.
</task>

<repair_quotes>
These quotes were not found in their cited passages: $failures. For each item, copy the exact text from the passage, or return it with an empty `quote` to withdraw it.
</repair_quotes>

<repair_numbers>
These statements hold a number or date that is not in the cited passage: $failures. Restate each with the passage's own values, or withdraw the item with an empty quote.
</repair_numbers>

<repair_long>
These quotes are longer than 300 characters: $failures. Shorten each to the span that states the obligation.
</repair_long>

<repair_missing>
These passage ids are missing from your answer: $missing. Add an item for each, or list it in `no_obligation_src_ids`.
</repair_missing>

<repair_close>
Return only the items you corrected or added, as JSON that matches the response schema.
</repair_close>

<repair_format>
Your answer did not match the response schema: $error. Return the whole result again, as JSON that matches the schema.
</repair_format>

<second_pass>
Based on the passages above, list any obligation on the supplier in passages $ids that the first reading missed, or return no items.
</second_pass>

## Why it works

- **It is the control.** EX0, the first rung of the extraction ladder, sends every passage of the RFP in one call with this plain instruction. Each later rung is judged against it.
- **No examples, the same schema, the same checks.** Like `extract.md` 0.4.0, it carries no examples since S-10 (ADR-028); the response schema and the repair messages match `extract.md`, and `verify` checks this rung's quotes too. EX1 therefore measures batching and the prompt contract (rules, decision table, the coverage check), not a change in examples or in quote checking.
- **Deliberately minimal.** No rules beyond the output format, and no decision table. Adding them here would hide what the contract buys.
- **Version 0.4.0** drops the examples with `extract.md`. **Version 0.3.0** added only what the code around every extract prompt needs: the repair messages for values not in the source and for quotes over 300 characters, and the second-pass task. The instruction stays plain, so EX0 remains the control the Master-Plan's ablation table describes, and EX1 still measures batching and the prompt contract together.
- **Decoding** matches `extract.md`, so the rungs differ only in what they test.
