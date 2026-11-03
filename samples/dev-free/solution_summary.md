# Solution summary: Request for Proposal: Electronic Signature Service

Status: UNREVIEWED_DRAFT. Every requirement below quotes the RFP, and a person must review this draft before anyone relies on it.

Run `20261103T021533Z-dev-rfp-3c582e4c-free`.

## 1. Requirements

### Submission hazards

- **REQ-0002** (must): Each bidder submits its proposal through the College's procurement portal as a single PDF of at most 20 pages by 2026-12-01 12:00 UTC. Source SRC-0015: "Proposals must be submitted through the College's procurement portal as a single PDF of no more than 20 pages by 2026-12-01 12:00 UTC."
- **REQ-0014** (must): The service must be live for students by 2027-01-11, the first day of spring enrollment. Source SRC-0030: "The service must be live for students by 2027-01-11, the first day of spring enrollment."

### Mandatory requirements

- **REQ-0003** (shall): The Supplier keeps an audit record of every signature event, including the signer's identity, the time, and the document version. Source SRC-0018: "The Supplier shall keep an audit record of every signature event, including the signer's identity, the time and the document version."
- **REQ-0004** (shall): The Supplier supports signing on current desktop and mobile browsers. Source SRC-0020: "support signing on current desktop and mobile browsers;"
- **REQ-0005** (shall): The Supplier sends a reminder to each signer who has not signed within 72 hours. Source SRC-0021: "send a reminder to each signer who has not signed within 72 hours."
- **REQ-0007** (shall): The Supplier stores signed documents for ten years. Source SRC-0023: "The Supplier shall store signed documents for ten (10) years."
- **REQ-0009** (must): The service must integrate with the College's student records system through its existing REST API. Source SRC-0025: "The service must integrate with the College's student records system through its existing REST API."
- **REQ-0011** (shall): The service shall be available 99.5% of the time in each calendar month, excluding planned maintenance announced five working days in advance. Source SRC-0027: "The service shall be available 99.5% of the time in each calendar month, excluding planned maintenance announced five working days in advance."

### Optional requirements

- **REQ-0006** (should): The Supplier should provide templates for the College's twelve most used forms. Source SRC-0022: "The Supplier should provide templates for the College's twelve most used forms."
- **REQ-0008** (should): The Supplier should migrate the signed records held in the current tool by 2027-02-28. Source SRC-0024: "The Supplier should migrate the signed records held in the current tool by 2027-02-28."
- **REQ-0010** (may): Bidders may propose an on-premises deployment option. Source SRC-0026: "Bidders may propose an on-premises deployment option."
- **REQ-0012** (should): The Supplier should respond to severity-one incidents within one hour, at any time of day. Source SRC-0028: "The Supplier should respond to severity-one incidents within one hour, at any time of day."

Quotes: 21 verbatim, 0 normalized, 0 rejected (listed in `rejected.jsonl`). Also found, not listed: 9 background, 0 not binding, 0 out of scope.

## 2. Approach

- **APP-001** (REQ-0002, REQ-0014): Bid compliance: assemble the proposal as a single PDF, verify it meets the 20-page limit, and submit it via the procurement portal before 2026-12-01 12:00 UTC. Ensure the service goes live for students by the first day of spring enrollment on 2027-01-11. Basis: The instructions mandate the submission format, page limit, deadline, and live date. Portal reliability is assumed.
- **APP-002** (REQ-0003, REQ-0007): Signature audit and retention: maintain an audit record of every signature event, capturing signer identity, time, and document version, and store signed documents for ten years. Basis: The audit elements and the ten-year retention period are explicitly defined in the requirements.
- **APP-003** (REQ-0004, REQ-0005): Browser compatibility and reminders: support signing across current desktop and mobile browsers, and send an automated reminder to any signer who has not completed signing within 72 hours. Basis: Browser support and the 72-hour reminder timeframe are explicitly stated.
- **APP-004** (REQ-0009, REQ-0011): System integration and availability: integrate the service with the College's student records system using its existing REST API, and maintain 99.5% monthly availability excluding planned maintenance announced five working days in advance. Basis: The integration method and availability metrics, along with maintenance notice periods, are specified.

Not yet mapped to an approach item: REQ-0006, REQ-0008, REQ-0010, REQ-0012.

## 3. Risks

- **RSK-001**: Integration with the student records system via REST API (REQ-0009) encounters unexpected authentication or schema hurdles, delaying go-live past 2027-01-11.
  Condition: Requirement REQ-0014 mandates that the service go live by 2027-01-11, leaving only 41 days from contract award assuming a 2026-12-01 award date. Effect: The service fails to launch for students on the first day of spring enrollment, breaching contract terms.
  Owner: Integration architect. Trigger: API documentation is not provided within three days of contract award. Responses: Request API documentation and sandbox access prior to contract award. Prepare a fallback manual roster import mechanism if API integration is delayed. Residual: Manual import requires operational overhead and risks student friction during spring enrollment. Evidence: SRC-0025, SRC-0030.
- **RSK-002**: Support staff attempt to access historical signed records during the spring enrollment period before migration is finished, and cannot find them in the new system.
  Condition: Requirement REQ-0008 suggests migrating signed records held in the current tool by 2027-02-28, which is after the student go-live date of 2027-01-11. Effect: Administrative delays and compliance confusion occur when staff must query two separate systems during enrollment.
  Owner: Data migration lead. Trigger: Migration script testing reveals data format mismatches from the legacy tool. Responses: Prioritize migration of the most frequently accessed form templates before 2027-01-11. Provide staff with clear documentation on how to access legacy archives. Residual: Staff time is wasted navigating dual systems until full migration completes on 2027-02-28. Evidence: SRC-0024, SRC-0030.

## 4. Open questions

- Should templates for the College's twelve most used forms be included, and what are their specific formats? (SRC-0022)
- What is the migration scope and data volume for the signed records held in the current tool by 2027-02-28? (SRC-0024)
- How should the optional on-premises deployment option be priced and architected? (SRC-0026)
- What support channels and escalation paths are required to meet the one-hour response time for severity-one incidents at any time of day? (SRC-0028)
- What is the expected schema and rate limit for the College's existing REST API referenced in REQ-0009? (SRC-0025)
- Does the target go-live date of 2027-01-11 allow for a phased rollout to specific student cohorts, or must all students be supported simultaneously? (SRC-0030)
