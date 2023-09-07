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
                type="Complaint",
                feedback_type=body_json["complaint"].get("complaintFeedbackType", None),
                destination=body_json["mail"]["destination"],
                complained_recipients=[
                    r["emailAddress"]
                    for r in body_json["complaint"]["complainedRecipients"]
                ],
            ),
            received_at=time.time(),
        ),
    )
