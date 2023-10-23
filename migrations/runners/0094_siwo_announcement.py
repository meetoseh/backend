from itgs import Itgs
from typing import Set
from loguru import logger
from lib.email.send import send_email
from lib.shared.job_callback import JobCallback
import socket


async def up(itgs: Itgs) -> None:
    """Notifies users who requested it that the Sign in with Oseh feature is
    available
    """
    conn = await itgs.conn()
    cursor = conn.cursor("none")

    emails: Set[str] = set()

    response = await cursor.execute(
        """
        SELECT 
            email 
        FROM login_test_stats 
        WHERE 
            action = 'email_capture_email' 
            AND email IS NOT NULL 
            AND email != ''
            AND NOT EXISTS (
                SELECT 1 FROM users
                WHERE users.email = login_test_stats.email
            )
            AND NOT EXISTS (
                SELECT 1 FROM suppressed_emails
                WHERE suppressed_emails.email_address = login_test_stats.email
            )
        """
    )
    for row in response.results or []:
        emails.add(row[0])

    logger.debug(f"Found {len(emails)} emails to contact: {emails}")
    emails.add("paul@oseh.com")
    emails.add("tj@oseh.com")

    logger.debug(f"After adding founders there are {len(emails)} emails..")

    for email in emails:
        await send_email(
            itgs,
            email=email,
            subject="The feature you requested is now available",
            template="emailLaunchAnnouncement",
            template_parameters={},
            success_job=JobCallback(
                name="runners.emails.test_success_handler", kwargs=dict()
            ),
            failure_job=JobCallback(
                name="runners.emails.test_failure_handler", kwargs=dict()
            ),
        )

    logger.debug(f"Finished sending {len(emails)} emails")

    slack = await itgs.slack()
    await slack.send_oseh_bot_message(
        f"{socket.gethostname()} Scheduled {len(emails)} emails to be sent to users "
        "who requested to be notified about Sign in with Oseh (plus TJ and Paul)"
    )
