# HighLevel / App Portal Inbox Manual Workaround

Drop business-only HighLevel, DF, or Credit Tracker conversation exports/copies here when the API path is blocked or incomplete.

Accepted file types: CSV, JSON, TXT, MD.

Recommended CSV headers:

```csv
contact,phone,email,last message,date,direction,contact_id,conversation_id,lastMessageType,channel,source
```

Then run:

```sh
make highlevel-inbox-workaround
```

Output:

- `data/local/highlevel-inbox-poller/manual-inbox-workaround.csv`
- `data/local/highlevel-inbox-poller/manual-inbox-workaround.md`
- `data/local/highlevel-inbox-poller/app-portal-event-proof.jsonl` when the row is clearly Credit Tracker app, DisputeFox portal, App Message, or Mobile App SMS proof
- `data/local/highlevel-inbox-poller/app-portal-event-proof.md` readable proof summary

No replies are sent from this workaround. Plain SMS rows are not app/portal proof unless the channel/source, message type, or message text clearly identifies the Credit Tracker app, DisputeFox portal, App Message, or Mobile App SMS.

## Graduation Rule

Use browser screenshots as one-off visual proof. Treat an event as repeatable API/manual/import proof only after the copied/exported row preserves source mapping and writes a no-send receipt:

- `lastMessageType` or `messageType` clearly identifies `App Message`, `TYPE_APP_MESSAGE`, `Mobile App SMS`, or another app/portal type.
- `channel` or `source` clearly identifies Credit Tracker, DisputeFox portal/admin, App Message, or Mobile App SMS.
- `contact_id` and `conversation_id` are included when available; if one is missing, the row can prove the event but still needs contact resolution before any reply.
- `app-portal-event-proof.jsonl` contains the row with `proof_status=captured_from_manual_import_no_send`.

If those fields are not available, keep the screenshot or browser note as browser-only proof and do not mark the event as API/manual/import-backed.
