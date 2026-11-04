# `guard` on the CrackedPDFs test split

Revision `245bc98` of [CrackedPDFs](https://huggingface.co/datasets/volkthienpreecha/crackedpdfs), MIT License, checked against `evals/external/BENCHMARKS.sha256`, and scored by `bidwright-eval external crackedpdfs`. `guard`'s PDF scan ran on each file with no parser and no model call. A file counts as flagged when the scan found hidden text or refused the file. Only these scores are committed.

| Measure | Value |
|---|---|
| Files | 2,919: 973 injected, 1,946 benign |
| Injected files flagged (true positives) | 973 |
| Benign files flagged (false positives) | 973 |
| Precision | 0.500 |
| Recall | 1.000 |
| F1 | 0.667 |
| Accuracy | 0.667 |
| Files the scan refused, counted as flagged | 0, of which 0 benign |
| Seconds per file, mean and median | 0.024 and 0.017 |

Published F1 on the same split, from the CrackedPDFs paper (a preprint), beside this run:

| Detector | F1 |
|---|---|
| Hybrid structural detector | 0.960 |
| Rule baseline | 0.623 |
| PromptGuard on extracted text | 0.390 |
| `guard`'s PDF scan, this run | 0.667 |

`guard` was not tuned on this data, and it looks for hidden text, not for intent. The benchmark's benign confounders hide harmless text with the same techniques as the injected files, so a detector of hidden text flags them too, and precision carries that cost. In Bidwright a flagged file is not rejected: its hidden text is quarantined and shown to a person, so a false positive costs review time, not a lost requirement. An instruction in plain visible text is outside `guard`'s reach by design; other controls carry that case: `ingest` flags passages that read like an instruction to a model, the document text sits inside delimiters, the tool gateway checks every call, and every output stays `UNREVIEWED_DRAFT`.

## Files with each kind of hidden text

A file can hold more than one kind. `pdf_off_page` is text whose box lies wholly outside the page's crop box.

| Kind | Injected files | Benign files |
|---|---|---|
| `pdf_background_color` | 238 | 238 |
| `pdf_invisible` | 305 | 305 |
| `pdf_off_page` | 668 | 668 |
| `pdf_tiny_font` | 131 | 131 |

## Injected files flagged, by rendering regime

| Rendering regime | Flagged | Of | Recall |
|---|---|---|---|
| invisible_render_mode | 305 | 305 | 100.0% |
| normal_visible | 162 | 162 | 100.0% |
| tiny_font | 253 | 253 | 100.0% |
| white_text | 253 | 253 | 100.0% |

## Injected files flagged, by attack family

| Attack family | Flagged | Of | Recall |
|---|---|---|---|
| existing_stream_patch | 73 | 73 | 100.0% |
| header_footer_like | 68 | 68 | 100.0% |
| in_page_invisible_text | 74 | 74 | 100.0% |
| in_page_low_contrast_text | 62 | 62 | 100.0% |
| in_page_split_text_objects | 46 | 46 | 100.0% |
| in_page_tiny_text | 68 | 68 | 100.0% |
| in_page_white_text | 51 | 51 | 100.0% |
| layout_mimicry | 79 | 79 | 100.0% |
| margin_microtext | 61 | 61 | 100.0% |
| microglyph_steganography | 66 | 66 | 100.0% |
| near_margin_normal_font | 70 | 70 | 100.0% |
| plain_single_block | 52 | 52 | 100.0% |
| semantic_fragmentation | 57 | 57 | 100.0% |
| split_text_objects | 66 | 66 | 100.0% |
| steganographic_acrostic | 80 | 80 | 100.0% |

## Benign files flagged, by confounder family

| Confounder family | Flagged | Of | Share flagged |
|---|---|---|---|
| benign_acrostic_editorial_note | 80 | 80 | 100.0% |
| benign_existing_stream_note | 73 | 73 | 100.0% |
| benign_in_page_invisible_note | 126 | 126 | 100.0% |
| benign_in_page_split_layout | 112 | 112 | 100.0% |
| benign_in_page_tiny_footer | 136 | 136 | 100.0% |
| benign_in_page_white_watermark | 51 | 51 | 100.0% |
| benign_layout_mimicry_note | 79 | 79 | 100.0% |
| benign_low_contrast_watermark | 62 | 62 | 100.0% |
| benign_margin_microtext | 131 | 131 | 100.0% |
| benign_microglyph_registration_mark | 66 | 66 | 100.0% |
| benign_semantic_fragmentation_note | 57 | 57 | 100.0% |
| none | 0 | 973 | 0.0% |
