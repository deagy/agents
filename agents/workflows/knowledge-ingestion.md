# Knowledge Store Ingestion Workflow

1. Knowledge store steward records source ownership, processing authority, intended use, classification, retention, residency, deletion, tenant, and audience constraints.
2. Security and compliance reviewers assess sensitive-data handling and external embedding-provider restrictions before real content leaves the staging boundary.
3. Store steward parses the export into the canonical message format and samples normalization results against the source.
4. Run redaction and prompt-injection detection. Human-review representative samples and every unexpected sensitive-data category.
5. Ingest into a store partition whose access controls match the source classification. Record the parser version, embedding provider/model, configuration, and run identifier.
6. Evaluate retrieval with representative questions, negative access tests, stale/conflicting guidance tests, and citation verification.
7. Evidence curator records approvals and ingestion evidence without copying raw sensitive content.
8. Remove raw staging exports through the approved records process and schedule retention/deletion verification.

Do not ingest when ownership, consent/authority, classification, provider data-use terms, residency, retention, or deletion obligations are unresolved.
