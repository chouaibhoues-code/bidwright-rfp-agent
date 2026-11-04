# Solution summary: Request for Proposal: Electronic Signature Service

Status: UNREVIEWED_DRAFT. Every requirement below quotes the RFP, and a person must review this draft before anyone relies on it.

Run `20261104T195655Z-dev-rfp-db9eeb00-free`.

## 1. Requirements

### Submission hazards

- **REQ-0001** (must): Each bidder submits its proposal through the College's procurement portal as a single PDF of at most 20 pages by 2026-12-01 12:00 UTC. Source SRC-0015: "Proposals must be submitted through the College's procurement portal as a single PDF of no more than 20 pages by 2026-12-01 12:00 UTC."
- **REQ-0012** (must): The service must be live for students by 2027-01-11, the first day of spring enrollment. Source SRC-0032: "The service must be live for students by 2027-01-11, the first day of spring enrollment."

Hidden content quarantined: 1 items; small print: 0 passages; suspect passages: 0; see `review/quarantine.md`.
Requirement groups: 4, in `requirement_groups.jsonl`.
Discrepancies: 0, in `discrepancies.jsonl`.
Clarification questions: 0, in `clarification_questions.md`.
Contract flags for legal review: 0, in `contract_flags.jsonl`.

### Mandatory requirements

- **REQ-0002** (shall): The Supplier keeps an audit record of every signature event, including the signer's identity, the time and the document version. Source SRC-0020: "The Supplier shall keep an audit record of every signature event, including the signer's identity, the time and the document version."
- **REQ-0003** (shall): The Supplier supports signing on current desktop and mobile browsers. Source SRC-0022: "support signing on current desktop and mobile browsers;"
- **REQ-0004** (shall): The Supplier sends a reminder to each signer who has not signed within 72 hours. Source SRC-0023: "send a reminder to each signer who has not signed within 72 hours."
- **REQ-0006** (shall): The Supplier stores signed documents for ten years. Source SRC-0025: "The Supplier shall store signed documents for ten (10) years."
- **REQ-0008** (must): The service must integrate with the College's student records system through its existing REST API. Source SRC-0027: "The service must integrate with the College's student records system through its existing REST API."
- **REQ-0010** (shall): The service is available 99.5% of the time in each calendar month, excluding planned maintenance announced five working days in advance. Source SRC-0029: "The service shall be available 99.5% of the time in each calendar month, excluding planned maintenance announced five working days in advance."

### Optional requirements

- **REQ-0005** (should): The Supplier should provide templates for the College's twelve most used forms. Source SRC-0024: "The Supplier should provide templates for the College's twelve most used forms."
- **REQ-0007** (should): The Supplier should migrate the signed records held in the current tool by 2027-02-28. Source SRC-0026: "The Supplier should migrate the signed records held in the current tool by 2027-02-28."
- **REQ-0009** (may): A bidder may propose an on-premises deployment option. Source SRC-0028: "Bidders may propose an on-premises deployment option."
- **REQ-0011** (should): The Supplier should respond to severity-one incidents within one hour, at any time of day. Source SRC-0030: "The Supplier should respond to severity-one incidents within one hour, at any time of day."

Quotes: 12 verbatim, 0 normalized, 0 rejected (listed in `rejected.jsonl`). Also found, not listed: 0 background, 0 not binding, 0 out of scope.

## 2. Approach

- **APP-001** (REQ-0001, REQ-0012): Bid compliance and delivery: assemble the proposal as a single PDF of at most 20 pages and submit it through the College's procurement portal by 2026-12-01 12:00 UTC, and ensure the service is live for students by 2027-01-11, the first day of spring enrollment. Basis: The portal submission deadline, file format, and page limit are explicitly stated, as is the mandatory go-live date for spring enrollment.
- **APP-002** (REQ-0003, REQ-0004): Signing platform: support signing on current desktop and mobile browsers, and send a reminder to each signer who has not signed within 72 hours. Basis: The browser environments and the 72-hour reminder window are specified in the requirements.
- **APP-003** (REQ-0002, REQ-0006): Audit and records: maintain an audit record of every signature event including signer identity, time, and document version, and store signed documents for ten years. Basis: The required audit details and the ten-year retention period are defined.
- **APP-004** (REQ-0008): System integration: integrate the service with the College's student records system through its existing REST API. Basis: The integration target and method via existing REST API are defined.
- **APP-005** (REQ-0010): Operations and availability: ensure the service is available 99.5% of the time in each calendar month, excluding planned maintenance announced five working days in advance. Basis: The availability percentage, calculation period, and planned maintenance notification lead time are stated.

Not yet mapped to an approach item: REQ-0005, REQ-0007, REQ-0009, REQ-0011.

## 3. Risks

- **RSK-001**: The final assembled proposal exceeds 20 pages or the upload is delayed past 2026-12-01 12:00 UTC.
  Condition: Proposal submission is restricted to a single PDF of at most 20 pages, due by 2026-12-01 12:00 UTC (SRC-0015). Effect: The proposal is rejected outright without evaluation.
  Owner: Bid manager. Trigger: Draft proposal exceeds 18 pages one week before the deadline, or portal upload is attempted less than 4 hours before 12:00 UTC. Responses: Enforce a strict 18-page budget for the draft to leave a two-page safety margin. Perform a dry-run upload of a dummy PDF via the procurement portal one week prior to the deadline. Residual: A technical portal outage during the final upload window. Evidence: SRC-0015.
- **RSK-002**: Integration, testing, or user acceptance delays push the deployment past the spring enrollment start date.
  Condition: The service must go live by 2027-01-11 for spring enrollment, leaving only 41 calendar days from the bid deadline of 2026-12-01 (SRC-0032). Effect: Students cannot sign enrollment documents digitally during the peak spring enrollment period.
  Owner: Delivery lead. Trigger: API integration testing is not completed two weeks before the go-live date. Responses: Pre-build and test the student records system REST API integration connector during the bid phase before formal award. Establish a fallback manual paper signing process for spring enrollment day if the digital service launch slips. Residual: Student friction and manual administrative overhead if the go-live date is missed. Evidence: SRC-0032.
- **RSK-003**: Students or staff require access to historical signed records during the gap between go-live and migration completion, but the records are still trapped in the legacy tool.
  Condition: The migration of signed records held in the current tool is scheduled for completion by 2027-02-28 (SRC-0026), which is after the go-live date of 2027-01-11 (SRC-0032). Effect: Inability to reference past documents leads to administrative compliance failures and user confusion.
  Owner: Data migration lead. Trigger: A support ticket requests a historical record stored in the legacy tool during January 2027. Responses: Accelerate the migration of signed records to finish prior to the 2027-01-11 go-live date. Provide designated staff with read-only access to the legacy tool until migration is fully complete. Residual: Dual-system lookup overhead for staff during the transition period. Evidence: SRC-0026, SRC-0032.

## 4. Open questions

- Which specific documents comprise the College's twelve most used forms for template provision? (SRC-0024)
- What is the data structure and volume of the signed records in the current tool to be migrated by 2027-02-28? (SRC-0026)
- Should the optional on-premises deployment be priced separately, and what infrastructure constraints apply? (SRC-0028)
- What support ticketing system or communication channel should be used for responding to severity-one incidents within one hour? (SRC-0030)
- What is the exact schema and rate limit of the College's existing REST API for the student records system mentioned in REQ-0008? (SRC-0027)
- Will the College grant immediate contract award notification after the 2026-12-01 submission to allow sufficient lead time for the 2027-01-11 go-live? (SRC-0015, SRC-0032)
