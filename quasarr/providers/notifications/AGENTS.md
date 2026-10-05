# quasarr/providers/notifications/ - Notifications

## Purpose

Multi-provider user notifications (Discord webhook, Telegram bot, Pushover) with a single entry point and per-type/per-provider toggles.

## Ownership

`__init__.py` (`send_notification`), `discord.py`, `telegram.py`, `pushover.py`, `helpers/` (frozen message dataclasses, `NotificationType` enum, `message_builder`, abstract formatter).

## Local Contracts

- For sending product notifications, callers use `send_notification(shared_state, title, case, imdb_id=, details=, source=)` plus the `NotificationType` enum for `case`; it reads `shared_state.values["notification_settings"]` (refreshed by `storage/setup/notifications.py`) and fans out to providers independently - provider failures are isolated, and it returns True if any provider succeeded. Known exceptions to that funnel: `storage/setup/notifications.py` (the settings UI/test flow) calls `build_notification_message` and the provider `send`/`inspect_destination` functions directly, and `api/__init__.py` imports the notification-type label helpers.
- Adding a notification type = new `NotificationType` enum value + label in `notification_types.py` + branch in `message_builder.build_notification_message`.
- Adding a provider = `AbstractNotificationFormatter` subclass implementing the four `render_*` methods + `send(shared_state, message, silent) -> bool` + wiring in all three entry points in `__init__.py` + adding it to `NOTIFICATION_PROVIDERS` in `quasarr/constants/__init__.py` + credential fields, validation, and toggle/silent defaults in `storage/setup/notifications.py`. Pushover has no editable tracked reference, so tracked and lifecycle calls send independently on each enabled outcome.
- Pushover messages use escaped HTML (`<b>` headings and fact labels, plus inline `<a>` links preserving each entry's full text), with the title sent only in the API title field and `html=1`. Bodies stay within 1024 characters without cutting tags or entities; oversized entries are skipped. Silent sends use priority `-2`; manual CAPTCHA fallback notifications use priority `+1`, and all other non-silent notifications use `0`.
- Pushover poster notifications stream `image_url` with the shared user-agent, read at most 5 MiB plus one byte before rejecting oversized attachments, and close the response on every path. Attachments require an image content type and nonempty payload. Fetch or validation failures fall back to text delivery without logging the URL or response details.
- Pushover `disabled` lifecycle alerts always include the manual CAPTCHA action, even when the initial `captcha` notification is disabled. Other lifecycle outcomes retain their existing entries.
- Message dataclasses are frozen; entries are passed as tuples.
- Discord protected-release notifications use `wait=true`; message ID, webhook fingerprint, current notification case, and effective silence state are persisted inside that release's existing `protected` JSON record. Every enabled lifecycle outcome edits the tracked message. At runtime, a transition from a silent previous case to an enabled non-silent current case also sends a short follow-up so Discord produces the configured alert; other transitions do not add a message. Disabled outcome types neither edit nor advance state. The case advances after each delivered edit, including the nonterminal SponsorsHelper-disable state; a silent-to-non-silent state advances only after its required follow-up succeeds, so a later outcome retries a failed alert. If no tracked message exists or an edit fails, the enabled outcome is sent normally as a fallback; a disabled-state fallback stores its replacement message reference for the later manual outcome. Tracked sends skip message construction when no configured provider enables the notification type.

## Work Guidance

(none beyond the contracts above)

## Verification

- Targeted test: `test_notifications.py`; full suite: `uv run python -X utf8 -m unittest discover -s tests`

## Child DOX Index

None.
