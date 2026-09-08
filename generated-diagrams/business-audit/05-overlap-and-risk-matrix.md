# Overlap and risk matrix

| Area | Overlap or debt | Why it exists today | Current impact | Suggested interpretation |
| --- | --- | --- | --- | --- |
| YouForm ingress | One lambda handles four business domains | Reuse of one webhook endpoint and shared parsing utilities | High cognitive load, more branching, harder audits | Functional but architecturally dense |
| Delete policy | Guardrail exists only in Streamlit | Fastest way to prevent accidental deletion | Critical policy bypass if API called directly | Business rule is not enforced at system boundary |
| Minor authorization lifecycle | State moves across webhook, validator, YouForm webhook and reminder | Reconciliation must work both before and after form arrival | Medium complexity but justified by async timing | Needs detailed docs and monitoring more than scale changes |
| Background check review | One final decision emerges from multiple document rows | PDF types have different extraction engines and timing | Medium complexity, legitimate domain complexity | Summary diagram must show aggregation, not single step |
| DynamoDB modeling | Several tables share generic schema with `gsi1..gsi4` | Faster module reuse | Low runtime cost, medium documentation cost | Over-generalized for current volume |
| Secrets usage | One shared secret stores Eventbrite token and form routing ids | Simplifies bootstrap | Medium blast radius for config mistakes | Clear but tightly coupled |
| Webhook trust boundary | No obvious signature verification in handlers | Simplicity, low current traffic | High security risk | Biggest non-scale architectural gap |
| API auth | Auth enforced in FastAPI middleware, not API Gateway | Faster implementation | Low scale risk, moderate purity debt | Acceptable for small scale, but note boundary mismatch |
