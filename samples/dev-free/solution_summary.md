# Solution summary: Request for Proposal: Electronic Signature Service

Status: UNREVIEWED_DRAFT. Every requirement below quotes the RFP, and a person must review this draft before anyone relies on it.

Run `20261103T030541Z-dev-rfp-3c582e4c-free`.

## 1. Requirements

### Submission hazards

- **REQ-0009** (must): Proposals must be submitted through the College's procurement portal as a single PDF of no more than 20 pages by 2026-12-01 12:00 UTC. Source SRC-0015: "Proposals must be submitted through the College's procurement portal as a single PDF of no more than 20 pages by 2026-12-01 12:00 UTC."
- **REQ-0023** (must): The service must be live for students by 2027-01-11, the first day of spring enrollment. Source SRC-0030: "The service must be live for students by 2027-01-11, the first day of spring enrollment."

### Mandatory requirements

- **REQ-0012** (shall): The Supplier keeps an audit record of every signature event, including the signer's identity, the time and the document version. Source SRC-0018: "The Supplier shall keep an audit record of every signature event, including the signer's identity, the time and the document version."
- **REQ-0013** (shall): The Supplier supports signing on current desktop and mobile browsers. Source SRC-0020: "support signing on current desktop and mobile browsers"
- **REQ-0014** (shall): The Supplier sends a reminder to each signer who has not signed within 72 hours. Source SRC-0021: "send a reminder to each signer who has not signed within 72 hours."
- **REQ-0016** (shall): The Supplier stores signed documents for ten years. Source SRC-0023: "The Supplier shall store signed documents for ten (10) years."
- **REQ-0018** (must): The service must integrate with the College's student records system through its existing REST API. Source SRC-0025: "The service must integrate with the College's student records system through its existing REST API."
- **REQ-0020** (shall): The service shall be available 99.5% of the time in each calendar month, excluding planned maintenance announced five working days in advance. Source SRC-0027: "The service shall be available 99.5% of the time in each calendar month, excluding planned maintenance announced five working days in advance."

### Optional requirements

- **REQ-0001** (none): The College invites proposals for a cloud electronic signature service. Source SRC-0006: "Kestrel Vale Community College (the College) invites proposals for a cloud electronic signature service."
- **REQ-0015** (should): The Supplier should provide templates for the College's twelve most used forms. Source SRC-0022: "The Supplier should provide templates for the College's twelve most used forms."
- **REQ-0017** (should): The Supplier should migrate the signed records held in the current tool by 2027-02-28. Source SRC-0024: "The Supplier should migrate the signed records held in the current tool by 2027-02-28."
- **REQ-0019** (may): Bidders may propose an on-premises deployment option. Source SRC-0026: "Bidders may propose an on-premises deployment option."
- **REQ-0021** (should): The Supplier should respond to severity-one incidents within one hour, at any time of day. Source SRC-0028: "The Supplier should respond to severity-one incidents within one hour, at any time of day."

Quotes: 30 verbatim, 0 normalized, 0 rejected (listed in `rejected.jsonl`). Also found, not listed: 17 background, 0 not binding, 0 out of scope.

## 2. Approach

- **APP-001** (REQ-0009, REQ-0023): Bid compliance and project delivery: submit the proposal as a single PDF of no more than 20 pages through the College's procurement portal by 2026-12-01 12:00 UTC, and ensure the service is live for students by 2027-01-11 for spring enrollment. Basis: The submission channel, PDF format, page limit, deadline, and live date are explicitly specified.
- **APP-002** (REQ-0012, REQ-0013, REQ-0016): Core signature and records: support signing on current desktop and mobile browsers, maintain an audit record of every signature event with signer identity, time, and document version, and store signed documents for ten years. Basis: Browser compatibility, audit requirements, and the ten-year retention period are stated.
- **APP-003** (REQ-0014, REQ-0018): Integration and workflow: send automated reminders to signers who have not signed within 72 hours, and integrate the service with the College's student records system via its existing REST API. Basis: The 72-hour reminder window and the requirement to use the existing REST API are defined.
- **APP-004** (REQ-0020): Service availability: maintain 99.5% service availability each calendar month, excluding planned maintenance announced five working days in advance. Basis: The uptime percentage and planned maintenance notice period are explicitly specified.

Not yet mapped to an approach item: REQ-0001, REQ-0015, REQ-0017, REQ-0019, REQ-0021.

## 3. Risks

- **RSK-001**: The final bid document exceeds 20 pages or portal congestion delays the upload past 2026-12-01 12:00 UTC.
  Condition: Proposals must be submitted through the College's procurement portal as a single PDF of no more than 20 pages by 2026-12-01 12:00 UTC under REQ-0009. Effect: The bid is disqualified immediately without evaluation.
  Owner: Bid manager. Trigger: The draft bid exceeds 18 pages one week before submission. Responses: Enforce a strict 18-page budget for all sections immediately. Upload the PDF 24 hours before the deadline. Residual: A technical outage of the procurement portal on the final day. Evidence: SRC-0015.
- **RSK-002**: Integration with the student records system REST API or environment setup experiences delays during the winter break.
  Condition: The service must be live for students by 2027-01-11 for spring enrollment under REQ-0023, leaving only 41 calendar days from the proposal deadline of 2026-12-01. Effect: Students cannot sign documents when spring enrollment opens, breaching the go-live requirement.
  Owner: Technical delivery lead. Trigger: API integration testing is not completed by 2026-12-20. Responses: Begin mock API integration prior to formal contract award. Negotiate a staged rollout prioritizing critical enrollment forms first. Residual: Limited time to resolve edge cases discovered during live student usage. Evidence: SRC-0030.

## 4. Open questions

- Does the College require a pure cloud electronic signature service, or should bidders price the optional on-premises deployment? (SRC-0006, SRC-0026)
- Should the scope include providing templates for the twelve most used forms and migrating signed records from the current tool by 2027-02-28? (SRC-0022, SRC-0024)
- What are the specific support channels and escalation paths expected for responding to severity-one incidents within one hour at any time of day? (SRC-0028)
- Does the student records system REST API support sandbox testing prior to the 2027-01-11 go-live date? (SRC-0030)
