# Proposal draft: Request for Proposal: Electronic Signature Service

Status: UNREVIEWED_DRAFT. Every requirement below quotes the RFP, and a person must review this draft before anyone relies on it.

## Understanding the College's requirements

The College requires a signature service live for student use by 2027-01-11 [REQ-0012]. We will deliver this by providing a service that supports signing on desktop and mobile browsers [REQ-0003] and integrates with the College’s student records system via the existing REST API [REQ-0008]. Our approach includes maintaining 99.5% availability [REQ-0010], sending automated reminders to signers after 72 hours [REQ-0004], generating audit records for every signature event [REQ-0002], and storing signed documents for ten years [REQ-0006]. We recognize the submission constraints: this proposal must be a single PDF of no more than 20 pages, submitted to the College's procurement portal by 2026-12-01 12:00 UTC [REQ-0001]. Adherence to these operational standards and submission deadlines is essential to ensuring proposal eligibility and meeting the spring enrollment schedule [REQ-0001, REQ-0012].

## Our approach to delivery

We will ensure bid compliance by assembling the tender as one PDF of no more than 20 pages for submission via the portal by 2026-12-01 12:00 UTC, with the service live for students by 2027-01-11 [APP-001]. We provide signing capabilities for all current desktop and mobile browsers and integrate with the student records system using the existing REST API [APP-002]. Every signature event is logged with user identity, time, and version [APP-003]. Signed documents are retained for ten years, and the system sends inactivity reminders after 72 hours [APP-003]. To ensure consistent access, we maintain 99.5% service availability each month [APP-004]. We will provide notification for any planned maintenance five working days before execution [APP-004]. This approach ensures the service meets all functional and operational requirements while maintaining the specified record-keeping standards.

## Risks and assumptions

The primary risk involves the College implementing a new records system mid-contract, which could break API integration and disrupt enrollment signing [RSK-001]. We will mitigate this by architecting the integration layer as an abstraction and including a change management clause requiring 90 days’ notice of technical specifications [RSK-001]. To manage the risk of missing historical documents during spring enrollment, we will prioritize migrating documents from the last 12 months before 2027-01-11 and directing users to the legacy system for older records via the UI [RSK-002]. We have several open questions requiring clarification: 
- Whether to include templates for the twelve most used forms and the process for identifying them [Q-01].
- If a formal quote for migration is required by 2027-02-28 [Q-01].
- Preferences regarding on-premises versus cloud deployment and severity-one incident SLAs [Q-02].
- Whether the 20-page proposal limit includes technical appendices [Q-03].
- If the legacy system will remain accessible in a read-only state until 2027-02-28 [Q-04].
