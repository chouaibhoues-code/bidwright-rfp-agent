# Assumptions

What the design takes as true, what breaks if it is false, how it is checked, and what happens if the check fails. Check ids refer to the research register in `context/Research-Register.md`, from Iteration 0b.

| Assumed | Breaks if false | Checked how | If false, then |
|---|---|---|---|
| Free-tier limits roughly match the community figures. Checked 2026-11-02 in AI Studio: Flash models allow 20 requests a day (the low end of the community 20-40), 3.5 Flash-Lite 500, and Gemma 4 14,400 at 16K input tokens a minute | Capacity and the paid budget | V-03 and the owner's AI Studio check | Recount capacity, and bring the paid-budget decision forward |
| Gemini 3 models need no sampling parameters: 3.6 and later ignore them, and Google advises keeping defaults on earlier Gemini 3 models such as 3.5 Flash-Lite | Decoding settings | C7-01 | Set the documented values per model in `config/models.yaml` |
| `docling-serve` keeps text exact enough for quote checks | The parser choice | S-01 and S-02 | pdfplumber stays the PDF parser, and DR-04 picks a fallback for tables |
| A local demo on free-tier Gemini with synthetic data is acceptable under Google's terms. This is a legal reading, not a settled fact. | The data rule | V-03 reads the current terms | Record the demo on `local` or on the paid tier |
| Synthetic RFPs stress the pipeline like real ones | What the scores mean | DR-10, and a realism check against QuRE | Raise the corpus's length and depth, and state the gap under known limits |
| Different model families reduce correlated errors. Published results also report errors that persist across vendors. | The independence of `assess` and `redteam` | Q-04, before Iteration 3 | Limit `assess` to entailment over the cited text with code pre-checks, report joint error, and spot-check 10 assessments by hand |
| 500 words approximates one page | Page-limit checks | Not checked | Use the RFP's own page measure where it states one |
| An hour means focused elapsed work by the owner and Claude together | `TIMELOG.md` | Not checked | Redefine the unit in `TIMELOG.md` |
| RFPs are in English | Language scope | Not checked | Study the language scope and state it |
| Whole-RFP inputs stay synthetic, and licensed public research datasets are acceptable for stage benchmarks | External benchmark runs | Licence checks (V-02), then runs through `bidwright-eval external` only | Drop that benchmark and record why |
| `/inputs` was meant to hold an RFP brief, possibly a short one, rather than a 20-25-page package | Input-size design and the `free` corpus rule | Not checked: the owner chose not to ask | A one-page brief written by the owner runs on `--profile local` at release, reported separately |
| The assignment's "using an LLM via Copilot/Cursor/opencode/Ollama" allows any free tier, as its ground rules suggest | The scored model path | Not checked | Ollama carries the scored path. At release, the `local` profile completes the thin thread on the development RFP. |
| In an RFP, "should" states a preference, not a requirement, so a "should" clause is OPTIONAL and never counts as a missed mandatory requirement | Missed-mandatory counts, and the extract prompt's decision table | The development RFP's gold uses this convention; real tenders vary | Make "should" depend on the RFP's own definition of its terms, which 	riage reads from Iteration 1 |
| gemini-3.8-flash on the free tier answers within the call timeout | Every eason node: approach, risk and draft | Two live runs on 2026-11-02 got 504s on every attempt, at 60 s and at 120 s, and a later probe got 429 RESOURCE_EXHAUSTED once the daily quota was spent | Record on --profile local, retry later, or use the paid fallback within the budget set at the Iteration 1 exit |

## Regulation

As of 2026-10-30, from secondary sources not yet checked against the Official Journal: Regulation (EU) 2026/1744 defers the AI Act's standalone high-risk duties to 2027-12-02, and Article 50's transparency duties apply from 2026-08-02. No design decision depends on this. Bidwright drafts only, submits nothing, and labels every output as an unreviewed AI draft.
