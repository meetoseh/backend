from emails.lib.events import EmailDeliveryNotification, EmailEvent
from emails.lib.helper import handle_event
from itgs import Itgs
import time


async def handle_delivery(itgs: Itgs, body_json: dict):
    """Handles the given verified email delivery from Amazon SES"""
    await handle_event(
        itgs,
        EmailEvent(
            message_id=body_json["mail"]["messageId"],
            notification=EmailDeliveryNotification(
                notification_type="Delivery",
            ),
            received_at=time.time(),
        ),
    )
