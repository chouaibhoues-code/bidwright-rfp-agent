# Solution summary: Request for Proposal: Electronic Signature Service

Status: UNREVIEWED_DRAFT. Every requirement below quotes the RFP, and a person must review this draft before anyone relies on it.

Run `20261103T011236Z-dev-rfp-3c582e4c-free`.

## 1. Requirements

### Submission hazards

- **REQ-0009** (must): Proposals must be submitted through the College's procurement portal as a single PDF of no more than 20 pages by 2026-12-01 12:00 UTC. Source SRC-0015: "Proposals must be submitted through the College's procurement portal as a single PDF of no more than 20 pages by 2026-12-01 12:00 UTC."
- **REQ-0018** (must): The service must integrate with the College's student records system through its existing REST API. Source SRC-0025: "The service must integrate with the College's student records system through its existing REST API."
- **REQ-0023** (must): The service must be live for students by 2027-01-11, the first day of spring enrollment. Source SRC-0030: "The service must be live for students by 2027-01-11, the first day of spring enrollment."

### Mandatory requirements

- **REQ-0012** (shall): The Supplier shall keep an audit record of every signature event, including the signer's identity, the time and the document version. Source SRC-0018: "The Supplier shall keep an audit record of every signature event, including the signer's identity, the time and the document version."
- **REQ-0013** (shall): The Supplier supports signing on current desktop and mobile browsers. Source SRC-0020: "support signing on current desktop and mobile browsers"
- **REQ-0014** (shall): The Supplier sends a reminder to each signer who has not signed within 72 hours. Source SRC-0021: "send a reminder to each signer who has not signed within 72 hours."
- **REQ-0016** (shall): The Supplier stores signed documents for ten years. Source SRC-0023: "The Supplier shall store signed documents for ten (10) years."
- **REQ-0020** (shall): The service shall be available 99.5% of the time in each calendar month, excluding planned maintenance announced five working days in advance. Source SRC-0027: "The service shall be available 99.5% of the time in each calendar month, excluding planned maintenance announced five working days in advance."

### Optional requirements

- **REQ-0015** (should): The Supplier should provide templates for the College's twelve most used forms. Source SRC-0022: "The Supplier should provide templates for the College's twelve most used forms."
- **REQ-0017** (should): The Supplier should migrate the signed records held in the current tool by 2027-02-28. Source SRC-0024: "The Supplier should migrate the signed records held in the current tool by 2027-02-28."
- **REQ-0019** (may): A bidder may propose an on-premises deployment option. Source SRC-0026: "Bidders may propose an on-premises deployment option."
- **REQ-0021** (should): The Supplier should respond to severity-one incidents within one hour, at any time of day. Source SRC-0028: "The Supplier should respond to severity-one incidents within one hour, at any time of day."

Quotes: 30 verbatim, 0 normalized, 0 rejected (listed in `rejected.jsonl`). Also found, not listed: 18 background, 0 not binding, 0 out of scope.

## 2. Approach

- **APP-001** (REQ-0009, REQ-0018, REQ-0023): Bid compliance: assemble the proposal as a single PDF of at most 20 pages and submit it through the College's procurement portal by 2026-12-01 12:00 UTC, and ensure the service is live for students by 2027-01-11, the first day of spring enrollment, integrating with the College's student records system through its existing REST API. Basis: The instructions specify the format, page limit, deadline, go-live date, and API integration requirement. The order of submission is an assumption to ensure compliance.
- **APP-002** (REQ-0012, REQ-0016): Audit and document management: keep an audit record of every signature event, including the signer's identity, the time, and the document version, and store signed documents for ten years. Basis: The audit record details and the ten-year storage duration are explicitly stated. The underlying storage medium is an assumption.
- **APP-003** (REQ-0013, REQ-0014): Signing accessibility and notifications: support signing on current desktop and mobile browsers, and send a reminder to each signer who has not signed within 72 hours. Basis: Browser compatibility and the 72-hour reminder timeframe are explicitly stated. The reminder delivery channel is an assumption.
- **APP-004** (REQ-0020): Service availability: maintain service availability of 99.5% of the time in each calendar month, excluding planned maintenance announced five working days in advance. Basis: The availability percentage and planned maintenance notice period are explicitly stated.

Not yet mapped to an approach item: REQ-0015, REQ-0017, REQ-0019, REQ-0021.

## 3. Risks

- **RSK-001**: The final document exceeds 20 pages during last-minute edits, or portal congestion delays the 2026-12-01 12:00 UTC upload.
  Condition: The proposal must be submitted as a single PDF of no more than 20 pages by 2026-12-01 12:00 UTC under REQ-0009. Effect: The proposal is disqualified instantly without review, losing the bid entirely.
  Owner: Bid manager. Trigger: The draft reaches 18 pages one week before submission, or the portal is untested. Responses: Enforce a strict 18-page budget immediately. Perform a dry-run upload via the procurement portal one week before the deadline. Residual: A technical outage of the procurement portal in the final hour before the deadline. Evidence: SRC-0015.
- **RSK-002**: Integration complexities with the College's student records system REST API delay the go-live past 2027-01-11.
  Condition: The service must go live for students by 2027-01-11, leaving only 41 days from the submission deadline of 2026-12-01 to build, test, and integrate. Effect: The service fails to launch on the first day of spring enrollment, disrupting student registration.
  Owner: Integration lead. Trigger: API sandbox credentials are not provided within three days of contract award. Responses: Request API documentation and sandbox access prior to contract award. Build a mock API server to enable parallel frontend and backend integration testing. Residual: Undocumented rate limits or unexpected authentication quirks in the College's live REST API. Evidence: SRC-0025, SRC-0030.
- **RSK-003**: Resources are pulled away from migration to handle spring enrollment support, causing migration to slip past 2027-02-28.
  Condition: Migration of signed records held in the current tool is scheduled as a should requirement (REQ-0017) by 2027-02-28, while ten-year document storage (REQ-0016) is mandatory. Effect: Historical signed records remain trapped in the legacy tool, complicating audits and ten-year retention compliance.
  Owner: Data migration lead. Trigger: Migration script development is delayed past 2027-01-15 due to enrollment support priorities. Responses: Allocate dedicated data engineering resources separate from the core go-live delivery team. Define a prioritized batch migration schedule starting with the most recent records. Residual: Incomplete legacy records requiring manual data cleanup and exception handling. Evidence: SRC-0023, SRC-0024.

## 4. Open questions

- Should the supplier provide templates for the College's twelve most used forms, and how are these templates specified? (SRC-0022)
- What is the expected data volume for migrating the signed records held in the current tool by 2027-02-28? (SRC-0024)
- Is the optional on-premises deployment option required to be priced separately, and what are the infrastructure prerequisites? (SRC-0026)
- What support channels and escalation paths are expected for responding to severity-one incidents within one hour at any time of day? (SRC-0028)
- Does the College's existing REST API support webhook subscriptions, or must the service poll for record updates? (SRC-0025)
- What data format and schema are used by the current tool for storing signed records that need to be migrated by 2027-02-28? (SRC-0024)
