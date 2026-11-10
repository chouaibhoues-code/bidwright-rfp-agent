# Solution gate

Status: UNREVIEWED_DRAFT. Run `20261110T075309Z-dev-rfp-db9eeb00-free`. Reviewed `manifest.json` sha256:5c9d0e26703434d1aa8576b658b33e6b9eb8e6d7538d45aa927480ac08e903c6 and `options.json` sha256:591cd28185516fac1a3f0936c2f00e316cfce6c8ec2880c9666a0e442b4128e7.

## The chosen option

OPT-2, Alternative Partner-Assisted Integration: rank 1, total 1.75 of 4.
Use built-in APIs and migration features alongside a partner approach for managing timelines and custom integrations, excluding unsupported availability and FERPA controls.

The ranking is hypothetical: no approved bid policy is loaded.

## The ranking

| Rank | Option | Total | Failed gates | Cites unsupported claims |
|---|---|---|---|---|
| 1 | OPT-2 Alternative Partner-Assisted Integration | 1.75 | none | none |
| 2 | OPT-1 Standard API & Migration Baseline | 1.5 | none | none |
- OPT-2 EF-01: 2 of 4. Meets technical approach requirements via configured APIs and alternative handling for student PII.
- OPT-2 EF-02: 0 of 4. Does not provide the required service level and support assurances directly.
- OPT-2 EF-03: 3 of 4. Exceeds baseline integration by incorporating partner-assisted timeline and migration coordination.
- OPT-1 EF-01: 2 of 4. Meets core electronic signing and record-keeping through documented APIs, but lacks specific technical breadth for FERPA controls.
- OPT-1 EF-02: 0 of 4. Does not address service levels and incident response commitments.
- OPT-1 EF-03: 2 of 4. Meets migration and integration needs using built-in historic record migration and REST APIs.
- OPT-2 answers RG-001 as EXCLUDED; left out.
- OPT-2 answers RG-002 as CONFIG; claims CL-001, CL-002.
- OPT-2 answers RG-003 as EXCLUDED; left out.
- OPT-2 answers RG-004 as PARTNER; no claim: rests on the option's assumptions.
- OPT-2 answers DN-001 as ALTERNATIVE; no claim: rests on the option's assumptions.
- OPT-2 assumes: A third-party implementation partner can bridge timeline and attribute release gaps.
- OPT-1 answers RG-001 as EXCLUDED; left out.
- OPT-1 answers RG-002 as OOTB; claims CL-001, CL-002.
- OPT-1 answers RG-003 as EXCLUDED; left out.
- OPT-1 answers RG-004 as EXCLUDED; left out.
- OPT-1 answers DN-001 as EXCLUDED; left out.
- OPT-1 assumes: The buyer accepts standard integration and migration tools without custom availability or timeline guarantees.

## The capability map

| Need | Origin | Status | Claims | Note |
|---|---|---|---|---|
| RG-001 3 Instructions to bidders | RFP | GAP | none | no claim is supported |
| RG-002 Electronic signing, record keeping, and integration requirements | RFP | PARTIAL | CL-001, CL-002 | some claims are supported, or only in part |
| RG-003 Service availability and severity-one incident response | RFP | GAP | CL-003 | no claim is supported |
| RG-004 6 Timeline | RFP | GAP | none | no claim is supported |
| DN-001 FERPA-aware attribute release controls that filter PII for students with active disclosure blocks. | DOMAIN | GAP | none | no claim is supported |

## The work packages

| Code | Name | Effort (days) | Predecessors | Evidence | Claims |
|---|---|---|---|---|---|
| 1.1 | Signing and Storage | 10 to 20 | none | ASSUMPTION | none |
| 1.2 | Integration and Migration | 15 to 25 | 1.1 | CAPABILITY_EVIDENCE | CL-001, CL-002 |
| 2.1 | Timeline Execution | 5 to 10 | 1.2 | ASSUMPTION | none |

## Assumptions and ground rules

- Assumption 1 (ASSUMPTION): A third-party implementation partner can bridge timeline and attribute release gaps.
- Assumption 2 (RFP_SOURCE): Proposal submission instructions and portal requirements are excluded from the solution scope.
- Assumption 3 (RFP_SOURCE): Service availability and severity-one incident response requirements are excluded from the first release.
- Ground rule 1 (RFP_SOURCE): Document retention follows the ten-year period stated in the RFP.

## The manifest's checks

| Check | Passed | Detail |
|---|---|---|
| tree | yes |  |
| hundred_percent | no | REQ-0001; REQ-0011 |
| backward_trace | yes |  |
| dictionary | yes |  |
| effort | yes |  |
| schedule | yes |  |
| provenance | yes |  |
| win_theme_proof | yes |  |
| no_prices_or_dates | yes |  |

## Technology claims

| Claim | Library | Verdict | Reason |
|---|---|---|---|
| TC-01 | none | NOT_CHECKABLE | names no library |
| TC-02 | none | NOT_CHECKABLE | names no library |

## Risks

- RSK-001: Integration and migration delays push the live date past 2027-01-11. (Delivery lead)

## The bid signal

UNDETERMINED.
Missing for a signal: bid policy.

## Research

the research pack `higher-education-procurement`, version 1

## How to decide

    bidwright approve 20261110T075309Z-dev-rfp-db9eeb00-free --role ROLE [--option OPT-n] [--edit FILE] [--override REASON] [--reject REASON]

An edit file is a YAML list of `{field, value}`. The fields an edit may change are `work_packages[<code>].effort.low_days`, `work_packages[<code>].effort.high_days`, `work_packages[<code>].predecessors`, `work_packages[<code>].scope`, `work_packages[<code>].exclusions`, `work_packages[<code>].acceptance`, `assumptions[<n>].text`, `ground_rules[<n>].text`; `<n>` counts from 1, as the manifest lists them.
