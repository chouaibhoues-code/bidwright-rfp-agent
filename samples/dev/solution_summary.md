# Solution summary: Request for Proposal: Electronic Signature Service

Status: UNREVIEWED_DRAFT. Every requirement below quotes the RFP, and a person must review this draft before anyone relies on it.

Run `20261104T211354Z-dev-rfp-db9eeb00-paid`.

## 1. Requirements

### Submission hazards

- **REQ-0001** (must): Proposals must be submitted through the College's procurement portal as a single PDF of no more than 20 pages by 2026-12-01 12:00 UTC. Source SRC-0015: "Proposals must be submitted through the College's procurement portal as a single PDF of no more than 20 pages by 2026-12-01 12:00 UTC."

Hidden content quarantined: 1 items; small print: 0 passages; suspect passages: 0; see `review/quarantine.md`.
Requirement groups: 4, in `requirement_groups.jsonl`.
Discrepancies: 0, in `discrepancies.jsonl`.
Clarification questions: 0, in `clarification_questions.md`.
Contract flags for legal review: 0, in `contract_flags.jsonl`.

### Mandatory requirements

- **REQ-0002** (shall): The Supplier shall keep an audit record of every signature event, including the signer's identity, the time and the document version. Source SRC-0020: "The Supplier shall keep an audit record of every signature event, including the signer's identity, the time and the document version."
- **REQ-0003** (shall): The Supplier shall support signing on current desktop and mobile browsers. Source SRC-0022: "(a) support signing on current desktop and mobile browsers;"
- **REQ-0004** (shall): The Supplier shall send a reminder to each signer who has not signed within 72 hours. Source SRC-0023: "(b) send a reminder to each signer who has not signed within 72 hours."
- **REQ-0006** (shall): The Supplier shall store signed documents for ten (10) years. Source SRC-0025: "The Supplier shall store signed documents for ten (10) years."
- **REQ-0008** (must): The service must integrate with the College's student records system through its existing REST API. Source SRC-0027: "The service must integrate with the College's student records system through its existing REST API."
- **REQ-0010** (shall): The service shall be available 99.5% of the time in each calendar month, excluding planned maintenance announced five working days in advance. Source SRC-0029: "The service shall be available 99.5% of the time in each calendar month, excluding planned maintenance announced five working days in advance."
- **REQ-0012** (must): The service must be live for students by 2027-01-11, the first day of spring enrollment. Source SRC-0032: "The service must be live for students by 2027-01-11, the first day of spring enrollment."

### Optional requirements

- **REQ-0005** (should): The Supplier should provide templates for the College's twelve most used forms. Source SRC-0024: "The Supplier should provide templates for the College's twelve most used forms."
- **REQ-0007** (should): The Supplier should migrate the signed records held in the current tool by 2027-02-28. Source SRC-0026: "The Supplier should migrate the signed records held in the current tool by 2027-02-28."
- **REQ-0009** (may): Bidders may propose an on-premises deployment option. Source SRC-0028: "Bidders may propose an on-premises deployment option."
- **REQ-0011** (should): The Supplier should respond to severity-one incidents within one hour, at any time of day. Source SRC-0030: "The Supplier should respond to severity-one incidents within one hour, at any time of day."

Quotes: 12 verbatim, 0 normalized, 0 rejected (listed in `rejected.jsonl`). Also found, not listed: 0 background, 0 not binding, 0 out of scope.

## 2. Approach

- **APP-001** (REQ-0001): Bid compliance: assemble the proposal as a single PDF of no more than 20 pages and submit it through the College's procurement portal by 2026-12-01 12:00 UTC. Basis: The instructions fix the format, page limit, and deadline. The submission timing is an assumption.
- **APP-002** (REQ-0002, REQ-0003, REQ-0006): Signature platform: support signing on current desktop and mobile browsers, keep an audit record of every signature event including signer identity, time, and document version, and store signed documents for ten (10) years. Basis: Browser support, audit components, and the 10-year retention period are stated. The storage location is an assumption.
- **APP-003** (REQ-0004, REQ-0008): Reminders and integrations: send a reminder to each signer who has not signed within 72 hours, and integrate with the College's student records system through its existing REST API. Basis: The 72-hour reminder and REST API integration requirement are specified. API credentials are an assumption.
- **APP-004** (REQ-0010, REQ-0012): Availability and go-live: ensure the service is live for students by 2027-01-11, the first day of spring enrollment, and maintain 99.5% availability in each calendar month excluding planned maintenance announced five working days in advance. Basis: The go-live date and 99.5% availability metric are stated. Maintenance scheduling details are an assumption.

Not yet mapped to an approach item: REQ-0005, REQ-0007, REQ-0009, REQ-0011.

## 3. Risks

- **RSK-001**: The final assembled proposal draft exceeds 20 pages during final formatting or the upload process starts too late to finish before the portal closes.
  Condition: The proposal must be submitted through the College's procurement portal as a single PDF of no more than 20 pages by 2026-12-01 12:00 UTC under REQ-0001. Effect: The tender is rejected without evaluation, leading to immediate disqualification from the bid.
  Owner: Bid manager. Trigger: The draft document reaches 18 pages before final annexes are attached. Responses: Enforce a strict 18-page limit on draft sections immediately. Upload a working draft to the procurement portal 24 hours prior to the 2026-12-01 deadline. Residual: A portal outage on the submission deadline remains a risk even after an early upload. Evidence: SRC-0015.
- **RSK-002**: Active student record lookups during spring enrollment require historical data that has not yet been migrated to the new tool.
  Condition: Migration of signed records held in the current tool is scheduled for completion by 2027-02-28 under REQ-0007, which falls after the 2027-01-11 student go-live date under REQ-0012. Effect: Staff and students must check two separate systems for records, leading to retrieval errors and compliance breaches.
  Owner: Data migration lead. Trigger: Migration script testing reveals data format mismatches with the legacy tool. Responses: Prioritize migration of active student cohorts before the 2027-01-11 go-live date. Implement a unified search interface bridging the new service and the current tool before go-live. Residual: A 48-day operational gap where historical records reside outside the primary platform. Evidence: SRC-0026, SRC-0032.

## 4. Open questions

- Should templates for the College's twelve most used forms be included, and in what format are they? (SRC-0024)
- What format are the signed records held in the current tool, and what is the expected volume for migration by 2027-02-28? (SRC-0026)
- What infrastructure and licensing assumptions apply to the optional on-premises deployment option? (SRC-0028)
- Should the one-hour response time for severity-one incidents apply 24/7, and through what communication channel? (SRC-0030)
- What is the expected data volume and schema format for the signed records held in the current tool that need to be migrated by 2027-02-28? (SRC-0026)
- Are there specific rate limits or concurrent connection caps enforced by the College's existing REST API for student records integration? (SRC-0027)
