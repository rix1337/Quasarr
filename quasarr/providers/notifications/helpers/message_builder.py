# -*- coding: utf-8 -*-
# Quasarr
# Project by https://github.com/rix1337

from quasarr.constants import QUASARR_AVATAR, SPONSORS_HELPER_URL
from quasarr.providers.log import info
from quasarr.providers.notifications.helpers.common import (
    build_solved_data,
    format_balance,
    format_number,
)
from quasarr.providers.notifications.helpers.notification_message import (
    NotificationFact,
    NotificationFactsEntry,
    NotificationLinkEntry,
    NotificationMessage,
    NotificationValueEntry,
)
from quasarr.providers.notifications.helpers.notification_types import (
    NotificationType,
    normalize_notification_type,
)


def _build_solved_entries(details):
    data = build_solved_data(details)
    if data is None:
        return ()

    entries = []
    for solver in data.get("solvers", []):
        facts = []
        attempts = solver["attempts"] if solver.get("has_attempts") else 0
        facts.append(NotificationFact("Attempts", str(attempts)))

        currency = solver.get("currency")
        if solver.get("cost") is not None:
            cost_text = format_number(solver["cost"])
            if currency:
                cost_text = f"{cost_text} {currency}"
            facts.append(NotificationFact("Cost", cost_text))

        if solver.get("balance") is not None:
            balance_text = format_balance(solver["balance"])
            if currency:
                balance_text = f"{balance_text} {currency}"
            facts.append(NotificationFact("Balance", balance_text))

        if facts:
            entries.append(
                NotificationFactsEntry(
                    title=solver["solver_display"],
                    facts=tuple(facts),
                )
            )

    if data.get("duration"):
        entries.append(NotificationValueEntry(title="Duration", value=data["duration"]))

    return tuple(entries)


def _build_reason_entry(details):
    if not isinstance(details, dict):
        return None

    reason = details.get("reason") or details.get("error")
    if not reason:
        return None

    return NotificationValueEntry(title="Reason", value=str(reason))


def build_notification_message(
    shared_state,
    title,
    case,
    details=None,
    source=None,
    image_url=None,
):
    notification_type = normalize_notification_type(case)
    if notification_type is None:
        info(f"Unknown notification case: {case}")
        return None

    entries = []
    thumbnail_url = None

    if notification_type == NotificationType.UNPROTECTED:
        description = "No CAPTCHA required. Links were added directly!"
    elif notification_type == NotificationType.SOLVED:
        if isinstance(details, dict) and details.get("method") == "manual":
            description = "CAPTCHA solved manually!"
        else:
            description = "CAPTCHA solved by SponsorsHelper!"
            entries.extend(_build_solved_entries(details))
    elif notification_type == NotificationType.FAILED:
        description = "Package marked as failed."
    elif notification_type == NotificationType.DISABLED:
        description = (
            "SponsorsHelper failed to solve the CAPTCHA! "
            "Please solve it manually to proceed."
        )
    elif notification_type == NotificationType.CAPTCHA:
        description = "Download will proceed, once the CAPTCHA has been solved."
        captcha_url = f"{shared_state.values['external_address']}/captcha"
        entries.append(
            NotificationLinkEntry(
                title="Solve CAPTCHA",
                text="Open this link to solve the CAPTCHA.",
                link_text="this link",
                url=captcha_url,
            )
        )
        if not shared_state.values.get("helper_active"):
            entries.append(
                NotificationLinkEntry(
                    title="SponsorsHelper",
                    text="Sponsors get automated CAPTCHA solutions!",
                    url=SPONSORS_HELPER_URL,
                )
            )
    elif notification_type == NotificationType.QUASARR_UPDATE:
        version = "latest"
        link = ""
        if isinstance(details, dict):
            version = details.get("version") or version
            link = details.get("link") or ""
        description = f"Please update to {version} as soon as possible!"
        if link:
            entries.append(
                NotificationLinkEntry(
                    title="Release notes at:",
                    text=f"GitHub.com: rix1337/Quasarr/{version}",
                    url=link,
                )
            )
        if not image_url:
            thumbnail_url = QUASARR_AVATAR
    elif notification_type == NotificationType.TEST:
        description = "This is a test notification from Quasarr UI configuration."
    else:
        info(f"Unknown notification case: {case}")
        return None

    if reason_entry := _build_reason_entry(details):
        entries.append(reason_entry)

    if source and source.startswith("http"):
        entries.append(
            NotificationLinkEntry(
                title="Source",
                text="View release details here",
                url=source,
            )
        )

    return NotificationMessage(
        title=title,
        description=description,
        entries=tuple(entries),
        image_url=image_url,
        thumbnail_url=thumbnail_url,
    )
