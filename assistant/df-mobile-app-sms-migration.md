# DF AutoFox Mobile App SMS Migration

## Goal

Move the routine AutoFox sequence away from regular SMS and into DisputeFox/Credit Tracker Mobile App SMS so members receive the same message content inside the mobile app/portal messaging channel.

## Current Blocker

DisputeFox is reachable at `https://secure.scorexer.com/jsp/admin/dashboard.jsp`, but the browser session is at the DF login screen. Brandon needs to complete the login or open DF already logged in before the sequence can be edited.

## Exact DF Change Needed

For each AutoFox sequence step that currently sends SMS:

1. Open `AutoFox`.
2. Find the active member outreach/onboarding sequence.
3. Open `View/Edit`.
4. For each step with an existing `SMS` action, open the SMS action and copy the full message body.
5. Click `Add New Action`.
6. Choose `Mobile App SMS`.
7. Paste the same message body.
8. Save the Mobile App SMS action.
9. Disable or delete the old regular SMS action only after confirming the Mobile App SMS action saved.
10. Keep the email action in the same step so email and app message can continue going out together.

## Message Body To Preserve

Use the same content from the approved routine outreach SMS:

```text
Hello {first_name}, thank you for your patience as our team continues working on your file. We are reviewing your latest import and preparing the next dispute-round update. Our goal is to keep making steady progress and keep you informed as new tracker updates come in. You can also check your Credit Tracker portal for updates, and you are welcome to reply here if you have any questions.
```

Confirm the merge field syntax inside DF before saving. If DF uses a different first-name variable, keep the wording and swap only the merge field.

## Test After Saving

Assign the updated AutoFox sequence to Erika Jordan or trigger the same test step. The expected result is a visible Credit Tracker/mobile-app message, not only a HighLevel SMS conversation entry.
