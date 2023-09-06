from emails.lib.events import EmailComplaintNotification, EmailEvent
from emails.lib.helper import handle_event
from itgs import Itgs
import time


async def handle_complaint(itgs: Itgs, body_json: dict):
    """Handles the given verified email complaint from Amazon SES"""
    await handle_event(
        itgs,
        EmailEvent(
            message_id=body_json["mail"]["messageId"],
            notification=EmailComplaintNotification(
                notification_type="Complaint",
                feedback_type=body_json["complaint"].get("complaintFeedbackType", None),
            ),
            received_at=time.time(),
        ),
    )
