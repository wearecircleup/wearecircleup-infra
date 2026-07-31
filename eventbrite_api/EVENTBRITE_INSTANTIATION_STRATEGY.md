# Eventbrite API Instantiation Strategy

## Purpose

This is the source of truth for producing one public Circle Up workshop through
the Eventbrite API. It defines endpoint order, fixed decisions, validation and
deletion. It does not prescribe Python implementation.

The model is a distinct, free, one-hour class each week for four to ten people,
usually at a cafe, bakery, restaurant, library or public space. These are not
recurring Eventbrite events because the topic, venue, copy and date can change
for every class.

`event_instantiation_input.template.json` is the machine-readable input. Its
keys are Eventbrite request attributes only. Human rules and explanations stay
in this document.

## Fixed Decisions

| Decision | Value | Reason |
| --- | --- | --- |
| Organization | `2998243227926` | Fixed Circle Up organization. Never accept it as user input. |
| Organizer | `121240412403` | Existing Circle Up organizer. It is sent as `event.organizer_id` on every event. |
| Currency | `USD` | A live `POST /v3/organizations/2998243227926/events/` validation on 2026-07-28 rejected `COP` with `event.currency: INVALID`. Do not send COP until Eventbrite enables it for this organization. |
| Format | Independent event | Weekly does not mean identical; no series parent or occurrences. |
| Attendance | One free ticket class | One unambiguous capacity and a simple QR check-in list. |
| Capacity | Human input, 3 through 10 | Default to 3. `event.capacity` and `ticket_class.quantity_total` must be identical. |
| Per-order limit | `maximum_quantity: 1` | Keeps registration equitable in a small group. |
| Publication | Draft, validate, then publish | A listing is never public while incomplete. |
| Corrections | Delete and recreate | This workflow does not use update as its normal correction mechanism. |
| FAQs | Preloaded Structured Content | Common participant information is consistent; it is not authored again for each class. |

## Eventbrite Defaults We Preserve

The following values were observed from a bare draft created and read back on
2026-07-28. The input omits them deliberately, so Eventbrite remains the
source of their default behavior.

| Attribute | Observed default | Circle Up decision |
| --- | --- | --- |
| `online_event` | `false` | Send it because the organizer selects in-person or online per event. |
| `listed` | `true` | Preserve it: public events should be discoverable. |
| `shareable` | `false` | Preserve it: do not make social sharing a system assumption. |
| `invite_only` | `false` | Preserve it: the ticket limit, not an invitation wall, controls attendance. |
| `show_remaining` | `false` | Preserve it: no scarcity counter on small community classes. |
| `capacity` | `0` | Do not preserve it: the human must choose a safe physical capacity. |

Do not add any of these flags merely to restate a default. Any future exception
must be a documented API policy change, not a hidden per-event toggle.

## Input Requirements

Complete every empty string and every `null` in the template before making an
API call.

- `event.name.html` is public HTML and must identify the specific class.
- `event.summary` is a concise public invitation, at most 140 characters.
- `event.start.utc`, `event.end.utc`, `ticket_class.sales_start`, and
  `ticket_class.sales_end` use ISO 8601 UTC timestamps, for example
  `2026-08-04T23:00:00Z`.
- `event.end.utc` is after `event.start.utc`; for this model, it is normally
  one hour after.
- Sales start is before sales end; sales end is on or before event start.
- `event.capacity` and `ticket_class.quantity_total` are the same integer from
  1 to 10.
- `ticket_class.maximum_quantity` is always `1`.
- For an in-person event, provide an existing `event.venue_id` and set
  `event.online_event` to `false`.
- For an online event, set `event.online_event` to `true` and leave
  `event.venue_id` empty. The online destination is configured separately in
  Eventbrite because it is not an event-create attribute in this contract.
- Reuse a venue ID. Venue discovery and creation are a separate administrative
  flow and are intentionally not part of this event form.
- Keep the two default attendee questions unless a documented reason requires
  their removal. Their `ticket_classes` arrays receive the created ticket ID
  before each `POST /v3/events/{event_id}/questions/` request.

`door_time`, `presented_by`, and `age_restriction` are not Eventbrite Event
attributes. Keep Structured Content limited to the text shown in Eventbrite's
native Overview plus the
standard FAQs. Confirm any age or access requirement with the venue; do not
represent it as an API field that Eventbrite will silently ignore.

For this simplified flow, the Eventbrite public summary is not authored
separately. It is derived directly from the event name.

The FAQs describe Circle Up accurately: it is a community research project,
has periodic and limited traceability, and has demonstrated community value.
They also explain the free activity, possible minimum consumption at commercial
venues, the exception for non-commercial venues, respectful conduct, privacy,
images, and the conditional continuity of the activity.

## Endpoint Flow

### 0. Resolve the venue once, outside this form

- `GET /v3/organizations/{organization_id}/venues/`
- If it is genuinely new: `POST /v3/organizations/{organization_id}/venues/`

Persist the returned venue ID in the venue register. Put only that value in
`event.venue_id` for in-person events. Do not create duplicate venue records
while creating weekly events.

### 1. Create the draft event

`POST /v3/organizations/{organization_id}/events/`

Send the `event` object from the template. Eventbrite requires `name`,
`start`, `end`, and `currency`; this contract additionally fixes the organizer,
the selected format and the human-selected capacity. The response supplies
`event_id`.

### 2. Create the ticket class

`POST /v3/events/{event_id}/ticket_classes/`

Send the `ticket_class` object. The quantity is the second capacity gate and
must match `event.capacity`. The exact `maximum_quantity: 1`, sales-window
request was validated live against this organization on 2026-07-28.

### 3. Create registration questions

`POST /v3/events/{event_id}/questions/`

For every object in `questions`, send it as the request body after replacing
its empty `ticket_classes` array with the new ticket class ID when the question
must apply only to that ticket. Keep only data needed to run the class and
learn from the community activity.

### 4. Upload the image separately

The image binary is intentionally not represented in the JSON: it is not an
Eventbrite Event attribute. Use Eventbrite's signed-media sequence:

1. `GET /v3/media/upload/?type=image-event-logo`
2. `POST {upload_url}` with the returned form fields and the JPEG or PNG file.
3. `POST /v3/media/upload/` with the upload token and a 2:1 crop mask.

Use JPEG or PNG under 10 MB, ideally 2160x1080 pixels. Confirm the current,
account-supported field or media association endpoint for setting the main
event image before automating the final attachment; do not guess an unverified
`logo_id` field.

### 5. Publish the listing content

`POST /v3/events/{event_id}/structured_content/{version_number}`

Put `version_number: 1` in the endpoint URL; send the body with `purpose:
"listing"`, `publish: true` and the full module list. The text module should
contain only the class-specific text for Eventbrite's native Overview plus the permanent FAQs. Do not add
extra editorial sections such as arrival, materials, or attendance reminders.
Structured Content is versioned and insert-only: send the full module list,
not a partial patch.

### 6. Validate before publication

`GET /v3/events/{event_id}/?expand=venue,ticket_classes,ticket_availability`

Check the draft has the correct organizer, physical or online format, venue,
time, currency, capacity, one free ticket, one-per-order limit, sales window,
questions and listing content. For an in-person class, also inspect the public
location in the Eventbrite UI. The Organizer app must see the event after it
goes live for QR check-in.

### 7. Publish and verify

- `POST /v3/events/{event_id}/publish/`
- `GET /v3/events/{event_id}/?expand=venue,ticket_classes,ticket_availability`

Confirm status is live, the listing is correct and the available inventory
equals the selected capacity before sharing the URL.

## Correction And Deletion Flow

Do not iterate a misconfigured event with `PATCH` in this operating model.
Before registrations, delete the faulty draft or live event and create a clean
replacement from a corrected input document:

1. Stop sharing the faulty event URL.
2. `DELETE /v3/events/{event_id}/`
3. `GET /v3/events/{event_id}/` and confirm Eventbrite reports `status:
   "deleted"`.
4. Correct the input JSON and restart at Step 1.

Deletion was validated live for this organization. Eventbrite retains a
readable record with deleted status; it does not turn that event back into a
draft. If registrations already exist, communicate the cancellation directly
to attendees before deletion and use Eventbrite's cancellation procedures when
applicable.

## Check-in And Reporting

Use the Eventbrite Organizer application to scan attendee QR codes. This API
does not write check-ins. It reads the resulting state through:

- `GET /v3/events/{event_id}/attendees/`
- `GET /v3/events/{event_id}/attendees/{attendee_id}/`

The local API's attendance and export endpoints can later move the minimal,
needed attendee answers and check-in state into a research datastore. No AWS
integration is required for this workflow.

## Sources

- [Eventbrite: Create events](https://www.eventbrite.com/platform/docs/create-events)
- [Eventbrite: Ticket classes](https://www.eventbrite.com/platform/docs/ticket-classes)
- [Eventbrite: Questions](https://www.eventbrite.com/platform/docs/questions)
- [Eventbrite: Event description and Structured Content](https://www.eventbrite.com/platform/docs/event-description)
- [Eventbrite: Image upload](https://www.eventbrite.com/platform/docs/image-upload)
- [Eventbrite: Attendees](https://www.eventbrite.com/platform/docs/attendees)
