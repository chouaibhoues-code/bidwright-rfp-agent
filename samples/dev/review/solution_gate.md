# Solution gate

Status: UNREVIEWED_DRAFT. Run `20261113T042518Z-dev-rfp-db9eeb00-free`. Reviewed `manifest.json` sha256:9952871808cc0f0577313dee7a01d7dbd11a2e284683ed80eb5b60259684d4c7 and `options.json` sha256:fed9490362830b870ac62c295d235bcc1cdb715beff9f3efb060f5af1d1c617e.

## The chosen option

OPT-2, Alternative migration-focused approach with partner signature: rank 1, total 2 of 4.
Focus on robust migration and partner-based digital signing, utilizing alternative data exchanges for service levels while excluding specific delivery dates.

The ranking is hypothetical: no approved bid policy is loaded.

## The ranking

| Rank | Option | Total | Failed gates | Cites unsupported claims |
|---|---|---|---|---|
| 1 | OPT-2 Alternative migration-focused approach with partner signature | 2 | none | none |
| 2 | OPT-1 Standard platform approach with partner signature and excluded timelines | 1.5 | none | none |
- OPT-2 EF-01: 2 of 4. Addresses technical approach via partner signing and document migration capabilities.
- OPT-2 EF-02: 1 of 4. Proposes alternative handling for service levels instead of direct contractual commitments.
- OPT-2 EF-03: 3 of 4. Exceeds standard integration by emphasizing structured migration with trial runs, reconciliation reports, and final cut-over.
- OPT-1 EF-01: 2 of 4. Meets digital signing through a partner product with audit logging, but leaves instructions and timelines unaddressed.
- OPT-1 EF-02: 0 of 4. Does not address service availability and incident response targets.
- OPT-1 EF-03: 2 of 4. Provides historic records and documents migration capabilities with trial runs and reconciliation reports.
- OPT-2 answers RG-001 as ALTERNATIVE; no claim: rests on the option's assumptions.
- OPT-2 answers RG-002 as PARTNER; claims CL-001, CL-002, CL-003.
- OPT-2 answers RG-003 as ALTERNATIVE; no claim: rests on the option's assumptions.
- OPT-2 answers RG-004 as EXCLUDED; left out.
- OPT-2 assumes: The buyer will accept alternative mechanisms for service level tracking and bidder instructions.
- OPT-1 answers RG-001 as EXCLUDED; left out.
- OPT-1 answers RG-002 as PARTNER; claims CL-001, CL-002, CL-003.
- OPT-1 answers RG-003 as EXCLUDED; left out.
- OPT-1 answers RG-004 as EXCLUDED; left out.
- OPT-1 assumes: The buyer accepts that specific service availability commitments and timeline deadlines are excluded from the initial scope.

## The capability map

| Need | Origin | Status | Claims | Note |
|---|---|---|---|---|
| RG-001 3 Instructions to bidders | RFP | GAP | none | no claim is supported |
| RG-002 Digital signing platform requirements | RFP | PARTIAL | CL-001, CL-002, CL-003 | some claims are supported, or only in part |
| RG-003 Service availability and incident response times | RFP | GAP | CL-004 | no claim is supported |
| RG-004 6 Timeline | RFP | GAP | CL-005 | no claim is supported |

## The work packages

| Code | Name | Effort (days) | Predecessors | Evidence | Claims |
|---|---|---|---|---|---|
| 1.1 | Signature platform setup | 5 to 10 | none | CAPABILITY_EVIDENCE | CL-001, CL-002 |
| 1.2 | API and Deployment | 8 to 15 | 1.1 | ASSUMPTION | none |
| 2.1 | Historic records migration | 10 to 20 | none | CAPABILITY_EVIDENCE | CL-003 |
| 2.2 | Alternative bidder instructions and service levels | 5 to 10 | none | ASSUMPTION | none |

## Assumptions and ground rules

- Assumption 1 (RFP_SOURCE): The buyer will accept alternative mechanisms for service level tracking and bidder instructions.
- Assumption 2 (RFP_SOURCE): The timeline requirement for the service to be live by 2027-01-11 is excluded from the initial scope.
- Ground rule 1 (RFP_SOURCE): Proposals must be submitted through the portal as a single PDF of no more than 20 pages by 2026-12-01 12:00 UTC.

## The manifest's checks

| Check | Passed | Detail |
|---|---|---|
| tree | yes |  |
| hundred_percent | no | REQ-0013 |
| backward_trace | yes |  |
| dictionary | yes |  |
| effort | yes |  |
| schedule | yes |  |
| provenance | no | ground rule 1: BI-001 |
| win_theme_proof | yes |  |
| no_prices_or_dates | yes |  |

## Technology claims

| Claim | Library | Verdict | Reason |
|---|---|---|---|
| TC-01 | none | NOT_CHECKABLE | names no library |

## Risks

- RSK-001: The final proposal exceeds 20 pages or is uploaded after the portal deadline closes. (Bid manager)
- RSK-002: Integration and deployment overrun the 2027-01-11 spring enrollment deadline. (Delivery lead)

## The bid signal

UNDETERMINED.
Missing for a signal: bid policy.

## Research

research pack

## How to decide

    bidwright approve 20261113T042518Z-dev-rfp-db9eeb00-free --role ROLE [--option OPT-n] [--edit FILE] [--override REASON] [--reject REASON]

An edit file is a YAML list of `{field, value}`. The fields an edit may change are `work_packages[<code>].effort.low_days`, `work_packages[<code>].effort.high_days`, `work_packages[<code>].predecessors`, `work_packages[<code>].scope`, `work_packages[<code>].exclusions`, `work_packages[<code>].acceptance`, `assumptions[<n>].text`, `ground_rules[<n>].text`; `<n>` counts from 1, as the manifest lists them.
