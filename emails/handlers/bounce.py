from emails.lib.events import (
    EmailBounceNotification,
    EmailBouncePermanent,
    EmailBounceTransient,
    EmailBounceUndetermined,
    EmailEvent,
)
from emails.lib.helper import handle_event
from itgs import Itgs
import time


async def handle_bounce(itgs: Itgs, body_json: dict):
    """Handles the given verified email bounce from Amazon SES"""
    bounce_type = body_json["bounce"]["bounceType"]
    bounce_subtype = body_json["bounce"]["bounceSubType"]

    if bounce_type == "Permanent":
        reason = EmailBouncePermanent(
            primary="Permanent",
            secondary=bounce_subtype,
        )
    elif bounce_type == "Transient":
        reason = EmailBounceTransient(
            primary="Transient",
            secondary=bounce_subtype,
        )
    elif bounce_type == "Undetermined":
        reason = EmailBounceUndetermined(
            primary="Undetermined",
            secondary=bounce_subtype,
        )
    else:
        raise NotImplementedError(
            f"Unknown bounce type: {bounce_type}, {bounce_subtype} for {body_json['mail']['destination']}"
        )

    await handle_event(
        itgs,
        EmailEvent(
            message_id=body_json["mail"]["messageId"],
            notification=EmailBounceNotification(
                notification_type="Bounce", reason=reason
            ),
            received_at=time.time(),
        ),
    )
