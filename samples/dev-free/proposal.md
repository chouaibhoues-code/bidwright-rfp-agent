# Proposal draft: Request for Proposal: Electronic Signature Service

Status: UNREVIEWED_DRAFT. Every requirement below quotes the RFP, and a person must review this draft before anyone relies on it.

## Our understanding of the College's needs

The College invites proposals for a cloud electronic signature service [REQ-0001]. The service must be live for students by 2027-01-11, the first day of spring enrollment [REQ-0023]. Proposals must be submitted through the College's procurement portal as a single PDF of no more than 20 pages by 2026-12-01 12:00 UTC [REQ-0009].

## How we would deliver

We will submit the proposal as a single PDF of no more than 20 pages through the College's procurement portal by 2026-12-01 12:00 UTC, and ensure the service is live for students by 2027-01-11 for spring enrollment [APP-001]. We support signing on current desktop and mobile browsers, maintain an audit record of every signature event with signer identity, time, and document version, and store signed documents for ten years [APP-002]. We send automated reminders to signers who have not signed within 72 hours, and integrate the service with the College's student records system via its existing REST API [APP-003]. We maintain 99.5% service availability each calendar month, excluding planned maintenance announced five working days in advance [APP-004].

## Risks and assumptions

The main risks to the bid and project involve document length, portal deadlines, and integration delays [RSK-001, RSK-002]. To prevent immediate disqualification, we would enforce an 18-page budget and upload the PDF 24 hours before the 2026-12-01 12:00 UTC deadline [RSK-001]. To address potential winter break delays affecting the student records system REST API integration, we would begin mock API integration prior to formal contract award and negotiate a staged rollout prioritizing critical enrollment forms first [RSK-002]. Open questions include whether the College requires a pure cloud service or optional on-premises deployment [Q-01], whether scope includes twelve form templates and migration by 2027-02-28 [Q-02], the specific support channels and escalation paths for one-hour severity-one incident responses [Q-03], and whether the student records system REST API supports sandbox testing before the 2027-01-11 go-live date [Q-04].
