# Risks and assumptions

The primary risk involves the College implementing a new records system mid-contract, which could break API integration and disrupt enrollment signing [RSK-001]. We will mitigate this by architecting the integration layer as an abstraction and including a change management clause requiring 90 days’ notice of technical specifications [RSK-001]. To manage the risk of missing historical documents during spring enrollment, we will prioritize migrating documents from the last 12 months before 2027-01-11 and directing users to the legacy system for older records via the UI [RSK-002]. We have several open questions requiring clarification: 
- Whether to include templates for the twelve most used forms and the process for identifying them [Q-01].
- If a formal quote for migration is required by 2027-02-28 [Q-01].
- Preferences regarding on-premises versus cloud deployment and severity-one incident SLAs [Q-02].
- Whether the 20-page proposal limit includes technical appendices [Q-03].
- If the legacy system will remain accessible in a read-only state until 2027-02-28 [Q-04].
