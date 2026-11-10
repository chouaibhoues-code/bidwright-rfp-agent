# Proposal draft: Request for Proposal: Electronic Signature Service

Status: UNREVIEWED_DRAFT. Every requirement below quotes the RFP, and a person must review this draft before anyone relies on it.

## Our understanding of the College's requirements

The College requires the service to be live for students by 2027-01-11, the first day of spring enrollment [REQ-0014]. Proposals must be submitted via the College's procurement portal as a single PDF of no more than 20 pages by 2026-12-01 12:00 UTC [REQ-0001]. The Supplier maintains an audit record of every signature event, including the signer's identity, the time, and the document version [REQ-0003], and supports signing on current desktop and mobile browsers [REQ-0004]. Signers who have not signed within 72 hours receive a reminder [REQ-0005], and signed documents are stored for ten (10) years [REQ-0007]. The service must integrate with the College's student records system through its existing REST API [REQ-0009], maintaining 99.5% availability in each calendar month, excluding planned maintenance announced five working days in advance [REQ-0011]. Additionally, the Supplier should provide templates for the College's twelve most used forms [REQ-0006], migrate signed records held in the current tool by 2027-02-28 [REQ-0008], respond to severity-one incidents within one hour at any time of day [REQ-0012], and may propose an on-premises deployment option [REQ-0010].

## Our proposed approach

We would configure electronic signing, document retention, and student record system integration [APP-001]. We would manage the live deployment timeline with the implementation partner [APP-002]. This fulfills the requirements for system configuration and partner implementation.

## Risks and open questions

The main risk is that integration and migration delays push the live date past 2027-01-11, leaving the service not live for the first day of spring enrollment [RSK-001]. To respond, the delivery lead would prioritize core signing integration before historic migration and engage the implementation partner immediately to compress package 1.2 [RSK-001]. Additionally, an open question remains regarding what the exact data volume and format are for the historic records to be migrated by 2027-02-28 under REQ-0008 [Q-01].
