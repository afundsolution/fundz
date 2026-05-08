# AutoFox / Credit Tracker Portal Message Setup

## Current Finding

The successful FUNDz pilot used HighLevel's Conversations message endpoint. That endpoint sent SMS and email, but it does not prove the message appears inside the Credit Tracker app/portal.

To make portal/app messages visible, FUNDz needs to trigger the AutoFox/Credit Tracker workflow that contains the actual portal/app-message action.

## Required AutoFox/Credit Tracker Workflow

Create or identify one workflow in AutoFox/Credit Tracker:

- Name: `FUNDz Routine Portal Touch`
- Trigger option A: contact is added to workflow by API
- Trigger option B: contact tag is added, for example `fundz_portal_touch`
- Action: send the Credit Tracker app/portal message
- Optional action: remove the trigger tag after the message sends
- Optional action: write a note/tag such as `fundz_portal_touch_sent`

If the portal message body can be dynamic, configure the workflow to read from a contact custom field:

- Field name: `FUNDz Portal Message`
- Field value: the approved FUNDz message text

Then set these in `.env.local`:

```text
AUTOFOX_PORTAL_WORKFLOW_ID=
AUTOFOX_PORTAL_TRIGGER_TAG=fundz_portal_touch
AUTOFOX_PORTAL_MESSAGE_FIELD_ID=
AUTOFOX_PORTAL_MESSAGE_FIELD_KEY=
```

At least one of `AUTOFOX_PORTAL_WORKFLOW_ID` or `AUTOFOX_PORTAL_TRIGGER_TAG` must be set.

## FUNDz Command

Preview only:

```sh
PYTHONPATH=scripts python3 scripts/fundz_autofox_portal_trigger.py --preview
```

Live trigger after owner approval:

```sh
PYTHONPATH=scripts python3 scripts/fundz_autofox_portal_trigger.py --live --approved-live-trigger
```

## Safety Rules

- Do not use this until the AutoFox workflow is confirmed to send a portal/app message.
- Do not trigger both workflow ID and tag unless the workflow is designed to avoid duplicate portal messages.
- Run preview first.
- Use only approved batch packets.
- Keep receipts under `data/local/semi-autonomous/receipts/`.
