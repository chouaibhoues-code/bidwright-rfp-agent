# Solution summary: Request for Proposal: Electronic Signature Service

Status: UNREVIEWED_DRAFT. Every requirement below quotes the RFP, and a person must review this draft before anyone relies on it.

Run `20261110T075309Z-dev-rfp-db9eeb00-free`.

## 1. Requirements

### Submission hazards

- **REQ-0001** (must): Each bidder submits its proposal through the College's procurement portal as a single PDF of no more than 20 pages by 2026-12-01 12:00 UTC. Source SRC-0015: "Proposals must be submitted through the College's procurement portal as a single PDF of no more than 20 pages by 2026-12-01 12:00 UTC."
- **REQ-0014** (must): The service must be live for students by 2027-01-11, the first day of spring enrollment. Source SRC-0032: "The service must be live for students by 2027-01-11, the first day of spring enrollment."

**Evaluation factors**, as the RFP states them
- Technical approach: 40% (SRC-0035)
- Service levels and support: 20% (SRC-0036)
- Integration and migration: 20% (SRC-0037)
- Price: 20% (SRC-0038), out of scope for the bid team

Hidden content quarantined: 1 item; small print: 0 passages; suspect passages: 0; see `review/quarantine.md`.
Requirement groups: 4, in `requirement_groups.jsonl`.
Discrepancies: 0, in `discrepancies.jsonl` and `brief.json`.
Clarification questions: 2, in `clarification_questions.md`.
Contract flags for legal review: 0, in `contract_flags.jsonl`.

### Mandatory requirements

- **REQ-0003** (shall): The Supplier keeps an audit record of every signature event, including the signer's identity, the time and the document version. Source SRC-0020: "The Supplier shall keep an audit record of every signature event, including the signer's identity, the time and the document version."
- **REQ-0004** (shall): The Supplier supports signing on current desktop and mobile browsers. Source SRC-0022: "support signing on current desktop and mobile browsers"
- **REQ-0005** (shall): The Supplier sends a reminder to each signer who has not signed within 72 hours. Source SRC-0023: "send a reminder to each signer who has not signed within 72 hours."
- **REQ-0007** (shall): The Supplier stores signed documents for ten (10) years. Source SRC-0025: "The Supplier shall store signed documents for ten (10) years."
- **REQ-0009** (must): The service must integrate with the College's student records system through its existing REST API. Source SRC-0027: "The service must integrate with the College's student records system through its existing REST API."
- **REQ-0011** (shall): The service shall be available 99.5% of the time in each calendar month, excluding planned maintenance announced five working days in advance. Source SRC-0029: "The service shall be available 99.5% of the time in each calendar month, excluding planned maintenance announced five working days in advance."

### Optional requirements

- **REQ-0006** (should): The Supplier should provide templates for the College's twelve most used forms. Source SRC-0024: "The Supplier should provide templates for the College's twelve most used forms."
- **REQ-0008** (should): The Supplier should migrate the signed records held in the current tool by 2027-02-28. Source SRC-0026: "The Supplier should migrate the signed records held in the current tool by 2027-02-28."
- **REQ-0010** (may): A bidder may propose an on-premises deployment option. Source SRC-0028: "Bidders may propose an on-premises deployment option."
- **REQ-0012** (should): The Supplier should respond to severity-one incidents within one hour, at any time of day. Source SRC-0030: "The Supplier should respond to severity-one incidents within one hour, at any time of day."

Quotes: 14 verbatim, 0 normalized, 0 rejected (listed in `rejected.jsonl`). Also found, not listed: 1 background, 1 not binding, 0 out of scope.

## 2. Approach

- **APP-001** (REQ-0003, REQ-0004, REQ-0005, REQ-0006, REQ-0007, REQ-0010, REQ-0008, REQ-0009): Electronic Signing and Integration: Configure electronic signing, document retention, and student record system integration. Basis: Configure electronic signing, document retention, and student record system integration.
- **APP-002** (REQ-0014): Partner Implementation: Manage the live deployment timeline with the implementation partner. Basis: Manage the live deployment timeline with the implementation partner.

Not yet mapped to an approach item: REQ-0001, REQ-0011.

### The chosen solution

Option: OPT-2.
Capability map: 0 COVERED, 4 GAP, 1 PARTIAL, 0 PARTNER.
Gaps: RG-001, RG-003, RG-004, DN-001.
Technology claims: 2 NOT_CHECKABLE.
Bid signal: UNDETERMINED; a person decides.

## 3. Risks

- **RSK-001**: Integration and migration delays push the live date past 2027-01-11.
  Condition: The service must be live for students by 2027-01-11 under REQ-0014, while work package 1.2 requires up to 25 days and follows package 1.1. Effect: The service is not live for the first day of spring enrollment.
  Owner: Delivery lead. Trigger: Work package 1.2 start date slips past the planned baseline. Responses: Prioritize core signing integration before historic migration. Engage the implementation partner immediately to compress package 1.2. Residual: Schedule pressure on the spring enrollment launch date. Evidence: SRC-0032.

## 4. Open questions

- What is the exact data volume and format for the historic records to be migrated by 2027-02-28 under REQ-0008?

## Appendix: domain research (external, unverified)

From the research pack `higher-education-procurement`, version 1.
- Standard: Systems must uphold 34 CFR § 99.30 (FERPA) by enforcing the 'school official exception,' ensuring data is used exclusively for contract fulfillment and prohibiting secondary data mining or model training. Sources: FERPA Student Record Signing: A Compliance Guide for Schools (tier 4), 34 CFR Part 99 Subpart D -- May an Educational Agency or Institution Disclose Personally Identifiable Information From Education Records? - eCFR (tier 1).
- Need: FERPA-aware attribute release controls that filter PII for students with active disclosure blocks. Sources: Understanding InCommon Federation Participant Operational Practices - services.pitt.edu (tier 2).
