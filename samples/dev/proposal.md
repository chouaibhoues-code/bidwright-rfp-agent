# Proposal draft: Request for Proposal: Electronic Signature Service

Status: UNREVIEWED_DRAFT. Every requirement below quotes the RFP, and a person must review this draft before anyone relies on it.

## Our understanding of the College's needs

The College requires proposal submission through its procurement portal as a single PDF of no more than 20 pages by 2026-12-01 12:00 UTC, and the service must be live for students by 2027-01-11, the first day of spring enrollment [REQ-0001, REQ-0013]. The service must integrate with the College's student records system through its existing REST API and be available 99.5% of the time in each calendar month, excluding planned maintenance announced five working days in advance [REQ-0008, REQ-0010]. The Supplier shall keep an audit record of every signature event, support signing on current desktop and mobile browsers, send a reminder to each signer who has not signed within 72 hours, and store signed documents for ten years [REQ-0002, REQ-0003, REQ-0004, REQ-0006]. Additionally, the Supplier should provide templates for the twelve most used forms, migrate signed records held in the current tool by 2027-02-28, respond to severity-one incidents within one hour at any time of day, and may propose an on-premises deployment option [REQ-0005, REQ-0007, REQ-0009, REQ-0011].

## Our approach

We would deploy partner e-signature capabilities and integrate with student records [APP-001]. We would migrate historic records and establish alternative service tracking and submission mechanisms [APP-002].

## Risks and assumptions

The final proposal exceeding 20 pages or uploading after the portal deadline risks rejection without evaluation [RSK-001]. We would enforce an 18-page limit on the draft and upload the PDF one working day prior to the deadline [RSK-001]. Integration and deployment overrunning the 2027-01-11 spring enrollment deadline risks students being unable to sign forms electronically on the first day [RSK-002]. We would prioritize core API integration tasks first and add engineering resources to work package 1.2 [RSK-002]. It remains an open question whether the buyer will accept alternative mechanisms for service level tracking and bidder instructions as stated in the assumptions [Q-01].
