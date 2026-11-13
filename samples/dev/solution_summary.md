# Solution summary: Request for Proposal: Electronic Signature Service

Status: UNREVIEWED_DRAFT. Every requirement below quotes the RFP, and a person must review this draft before anyone relies on it.

Run `20261113T042518Z-dev-rfp-db9eeb00-free`.

## 1. Requirements

### Submission hazards

- **REQ-0001** (must): Proposals must be submitted through the College's procurement portal as a single PDF of no more than 20 pages by 2026-12-01 12:00 UTC. Source SRC-0015: "Proposals must be submitted through the College's procurement portal as a single PDF of no more than 20 pages by 2026-12-01 12:00 UTC."
- **REQ-0013** (must): The service must be live for students by 2027-01-11, the first day of spring enrollment. Source SRC-0032: "The service must be live for students by 2027-01-11, the first day of spring enrollment."

**Evaluation factors**, as the RFP states them
- Technical approach: 40% (SRC-0035)
- Service levels and support: 20% (SRC-0036)
- Integration and migration: 20% (SRC-0037)
- Price: 20% (SRC-0038), out of scope for the bid team

Hidden content quarantined: 1 item; small print: 0 passages; suspect passages: 0; see `review/quarantine.md`.
Requirement groups: 4, in `requirement_groups.jsonl`.
Discrepancies: 0, in `discrepancies.jsonl` and `brief.json`.
Clarification questions: 0, in `clarification_questions.md`.
Contract flags for legal review: 0, in `contract_flags.jsonl`.

### Mandatory requirements

- **REQ-0002** (shall): The Supplier shall keep an audit record of every signature event, including the signer's identity, the time and the document version. Source SRC-0020: "The Supplier shall keep an audit record of every signature event, including the signer's identity, the time and the document version."
- **REQ-0003** (shall): The Supplier supports signing on current desktop and mobile browsers. Source SRC-0022: "support signing on current desktop and mobile browsers"
- **REQ-0004** (shall): The Supplier sends a reminder to each signer who has not signed within 72 hours. Source SRC-0023: "send a reminder to each signer who has not signed within 72 hours"
- **REQ-0006** (shall): The Supplier shall store signed documents for ten (10) years. Source SRC-0025: "The Supplier shall store signed documents for ten (10) years."
- **REQ-0008** (must): The service must integrate with the College's student records system through its existing REST API. Source SRC-0027: "The service must integrate with the College's student records system through its existing REST API."
- **REQ-0010** (shall): The service shall be available 99.5% of the time in each calendar month, excluding planned maintenance announced five working days in advance. Source SRC-0029: "The service shall be available 99.5% of the time in each calendar month, excluding planned maintenance announced five working days in advance."

### Optional requirements

- **REQ-0005** (should): The Supplier should provide templates for the College's twelve most used forms. Source SRC-0024: "The Supplier should provide templates for the College's twelve most used forms."
- **REQ-0007** (should): The Supplier should migrate the signed records held in the current tool by 2027-02-28. Source SRC-0026: "The Supplier should migrate the signed records held in the current tool by 2027-02-28."
- **REQ-0009** (may): Bidders may propose an on-premises deployment option. Source SRC-0028: "Bidders may propose an on-premises deployment option."
- **REQ-0011** (should): The Supplier should respond to severity-one incidents within one hour, at any time of day. Source SRC-0030: "The Supplier should respond to severity-one incidents within one hour, at any time of day."

Quotes: 13 verbatim, 0 normalized, 0 rejected (listed in `rejected.jsonl`). Also found, not listed: 1 background, 0 not binding, 0 out of scope.

## 2. Approach

- **APP-001** (REQ-0002, REQ-0003, REQ-0004, REQ-0005, REQ-0006, REQ-0008, REQ-0009): Partner e-Signature Integration: Deploy partner e-signature capabilities and integrate with student records. Basis: Deploy partner e-signature capabilities and integrate with student records.
- **APP-002** (REQ-0007, REQ-0001, REQ-0010, REQ-0011): Migration and Alternative Delivery: Migrate historic records and establish alternative service tracking and submission mechanisms. Basis: Migrate historic records and establish alternative service tracking and submission mechanisms.

Not yet mapped to an approach item: REQ-0013.

### The chosen solution

Option: OPT-2.
Capability map: 0 COVERED, 3 GAP, 1 PARTIAL, 0 PARTNER.
Gaps: RG-001, RG-003, RG-004.
Technology claims: 1 NOT_CHECKABLE.
Bid signal: UNDETERMINED; a person decides.

## 3. Risks

- **RSK-001**: The final proposal exceeds 20 pages or is uploaded after the portal deadline closes.
  Condition: Proposals must be submitted as a single PDF of no more than 20 pages by 2026-12-01 12:00 UTC under REQ-0001. Effect: The proposal is rejected without evaluation.
  Owner: Bid manager. Trigger: The draft exceeds 18 pages or upload has not started by 2026-11-30. Responses: Enforce an 18-page limit on the draft. Upload the PDF one working day prior to the deadline. Residual: A portal outage on the final day remains. Evidence: SRC-0015.
- **RSK-002**: Integration and deployment overrun the 2027-01-11 spring enrollment deadline.
  Condition: The service must be live for students by 2027-01-11 under REQ-0013, while work package 1.2 requires up to 15 days. Effect: Students cannot sign forms electronically on the first day of spring enrollment.
  Owner: Delivery lead. Trigger: Work package 1.2 slips past its scheduled start. Responses: Proritize core API integration tasks first. Add engineering resources to work package 1.2. Residual: Integration delays impacting the go-date. Evidence: SRC-0032.

## 4. Open questions

- Will the buyer accept alternative mechanisms for service level tracking and bidder instructions as stated in the assumptions?
