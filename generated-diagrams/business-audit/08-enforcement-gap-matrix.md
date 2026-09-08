# Enforcement gap matrix

| Rule | System of record | Enforcement layer | Bypass path | Why the gap matters |
| --- | --- | --- | --- | --- |
| No delete after registrations | Operational intent | Streamlit UI | Direct API call to `eventbrite_api` delete endpoint | User interface is not the final authority |
| Only real Eventbrite webhooks should create order snapshots | Order snapshot table | Payload-shape checks inside Lambda | Any POST with valid JSON and plausible `api_url` shape | Trust boundary is porous |
| Only real YouForm submissions should update legal or volunteer state | YouForm submission tables | `form_id` and payload-shape checks inside Lambda | Any POST with matching `form_id` and expected fields | A forged payload could mutate business state |
| Internal review should only be created by the intended backoffice form | Background submission row | Exact `form_id` and partition-key parse | Crafted POST with valid partition key | Hidden key is integrity glue, not authentication |
| Only approved admins should receive volunteer notifications | SES send step | Hardcoded allowlist in Lambda | Config/code change | Good local control, low bypass risk |
| Only terminal background outcomes should notify ops | Reviews summary row | Fingerprint + status check in Lambda | Manual replay with changed payload or code change | Mostly acceptable |
| Event publish should always rewrite minor links | Eventbrite listing content | Publish path in API | Event published outside API facade | Legal path silently detaches from event lifecycle |
| Reminder stop conditions should be accurate | Jobs table | Lambda decision logic | Bad event datetime data or stale order snapshot | Can create noisy or stale reminders |

## Reading guide

- `System of record` means where the truth ends up persisted or observed.
- `Enforcement layer` means the exact tier currently preventing misuse.
- `Bypass path` means the shortest realistic way the rule could be skipped without changing intended business meaning.
