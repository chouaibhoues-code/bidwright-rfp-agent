# Solution summary: Request for Proposal: Electronic Signature Service

Status: UNREVIEWED_DRAFT. Every requirement below quotes the RFP, and a person must review this draft before anyone relies on it.

Run `20261105T120916Z-dev-rfp-db9eeb00-free`.

## 1. Requirements

### Submission hazards

- **REQ-0001** (must): The bidder must submit their proposal through the College's procurement portal as a single PDF file of no more than 20 pages by 2026-12-01 12:00 UTC. Source SRC-0015: "Proposals must be submitted through the College's procurement portal as a single PDF of no more than 20 pages by 2026-12-01 12:00 UTC."
- **REQ-0012** (must): The service must be live for students by 2027-01-11, which is the first day of spring enrollment. Source SRC-0032: "The service must be live for students by 2027-01-11, the first day of spring enrollment."

**Evaluation factors**, as the RFP states them
- Technical approach: 40% (SRC-0035)
- Service levels and support: 20% (SRC-0036)
- Integration and migration: 20% (SRC-0037)
- Price: 20% (SRC-0038), out of scope for the bid team

Hidden content quarantined: 1 item; small print: 0 passages; suspect passages: 0; see `review/quarantine.md`.
Requirement groups: 4, in `requirement_groups.jsonl`.
Discrepancies: 0, in `discrepancies.jsonl` and `brief.json`.
Clarification questions: 5, in `clarification_questions.md`.
Contract flags for legal review: 0, in `contract_flags.jsonl`.

### Mandatory requirements

- **REQ-0002** (shall): The supplier shall keep an audit record of every signature event including the signer's identity, the time, and the document version. Source SRC-0020: "The Supplier shall keep an audit record of every signature event, including the signer's identity, the time and the document version."
- **REQ-0003** (shall): The supplier shall support signing on current desktop and mobile browsers. Source SRC-0022: "support signing on current desktop and mobile browsers"
- **REQ-0004** (shall): The supplier shall send a reminder to each signer who has not signed within 72 hours. Source SRC-0023: "send a reminder to each signer who has not signed within 72 hours."
- **REQ-0006** (shall): The supplier shall store signed documents for ten (10) years. Source SRC-0025: "The Supplier shall store signed documents for ten (10) years."
- **REQ-0008** (must): The service must integrate with the College's student records system through its existing REST API. Source SRC-0027: "The service must integrate with the College's student records system through its existing REST API."
- **REQ-0010** (shall): The service shall be available 99.5% of the time in each calendar month, excluding planned maintenance announced five working days in advance. Source SRC-0029: "The service shall be available 99.5% of the time in each calendar month, excluding planned maintenance announced five working days in advance."

### Optional requirements

- **REQ-0005** (should): The supplier should provide templates for the College's twelve most used forms. Source SRC-0024: "The Supplier should provide templates for the College's twelve most used forms."
- **REQ-0007** (should): The supplier should migrate the signed records held in the current tool by 2027-02-28. Source SRC-0026: "The Supplier should migrate the signed records held in the current tool by 2027-02-28."
- **REQ-0009** (may): Bidders may propose an on-premises deployment option. Source SRC-0028: "Bidders may propose an on-premises deployment option."
- **REQ-0011** (should): The supplier should respond to severity-one incidents within one hour, at any time of day. Source SRC-0030: "The Supplier should respond to severity-one incidents within one hour, at any time of day."

Quotes: 12 verbatim, 0 normalized, 0 rejected (listed in `rejected.jsonl`). Also found, not listed: 0 background, 0 not binding, 0 out of scope.

## 2. Approach

- **APP-001** (REQ-0001, REQ-0012): Bid compliance: assemble the tender as one PDF of no more than 20 pages and submit it via the portal by 2026-12-01 12:00 UTC, ensuring the service is live for students by 2027-01-11. Basis: The deadline and page limit are set by the procurement process, and the live date aligns with the start of spring enrollment.
- **APP-002** (REQ-0003, REQ-0008): Service features: provide signing capabilities for all current desktop and mobile browsers, and integrate with the student records system using the existing REST API. Basis: Browser compatibility is baseline for web services, and the use of the REST API is the stated method for student system integration.
- **APP-003** (REQ-0002, REQ-0004, REQ-0006): Signature management: log every signature event with user identity, time, and version while retaining all signed documents for ten years and sending reminders after 72 hours of inactivity. Basis: Automated logs and retention satisfy the record-keeping standards required for digital signing.
- **APP-004** (REQ-0010): Operational excellence: maintain 99.5% service availability each month, with planned maintenance notified five working days before execution. Basis: The service availability and maintenance notification period ensure minimal disruption to user access.

Not yet mapped to an approach item: REQ-0005, REQ-0007, REQ-0009, REQ-0011.

## 3. Risks

- **RSK-001**: The College implements a new records system mid-contract, causing the API integration to break and preventing identity or document verification.
  Condition: The College plans to replace its student records system during 2027 (SRC-0012), but the bid assumes integration with the current system's REST API (SRC-0027) must be functional by 2027-01-11. Effect: Disruption of enrollment signing processes and inability for the platform to verify student data, leading to a service outage.
  Owner: Delivery lead. Trigger: The College announces the procurement or go-live timeline for the new student records system. Responses: Draft a change management clause requiring the College to provide technical API specifications for the new system at least 90 days prior to switchover. Architect the integration layer as an abstraction to isolate the signing service from the specific records system API. Residual: Reliance on the College's communication regarding their infrastructure roadmap. Evidence: SRC-0012, SRC-0027.
- **RSK-002**: Users access the new service during the spring enrollment period but find historical documents are not present, appearing as missing.
  Condition: The service must be live on 2027-01-11 (SRC-0032), but the migration of existing signed records is not required until 2027-02-28 (SRC-0026), a gap of 48 days. Effect: High volume of support tickets regarding missing documentation, resulting in administrative overhead and a loss of user confidence in the platform.
  Owner: Project manager. Trigger: Helpdesk receives requests regarding missing records after 2027-01-11. Responses: Prioritize the migration of documents from the last 12 months for completion before 2027-01-11. Display a message in the new UI directing users to the legacy system for records created prior to 2027-01-11. Residual: 48 days of degraded user experience regarding historical record retrieval. Evidence: SRC-0032, SRC-0026.

## 4. Open questions

- Should the supplier include templates for the twelve most used forms, and how would these be identified? Also, does the College require a formal quote for the migration of records by 2027-02-28? (SRC-0024, SRC-0026)
- Does the College prefer an on-premises deployment over the default cloud service, and what are the specific SLAs expected for severity-one incidents beyond the one-hour response goal? (SRC-0028, SRC-0030)
- Does the 20-page proposal limit (REQ-0001) include technical appendices and security documentation, or are those exempt?
- Will the College maintain the legacy records system in a read-only state accessible to users until the 2027-02-28 migration deadline? (SRC-0026)

## Appendix: domain research (external, unverified)

From the research pack `higher-education-procurement`, version 1.
- Standard: Systems must uphold 34 CFR § 99.30 (FERPA) by enforcing the 'school official exception,' ensuring data is used exclusively for contract fulfillment and prohibiting secondary data mining or model training. Sources: FERPA Student Record Signing: A Compliance Guide for Schools (tier 4), 34 CFR Part 99 Subpart D -- May an Educational Agency or Institution Disclose Personally Identifiable Information From Education Records? - eCFR (tier 1).
- Need: FERPA-aware attribute release controls that filter PII for students with active disclosure blocks. Sources: Understanding InCommon Federation Participant Operational Practices - services.pitt.edu (tier 2).
