import secrets
from itgs import Itgs
import time
import touch_points.lib.touch_points as tp
import base64
import gzip


async def up(itgs: Itgs) -> None:
    conn = await itgs.conn()
    cursor = conn.cursor()

    uid = f"oseh_tpo_{secrets.token_urlsafe(16)}"
    await cursor.execute(
        """
INSERT INTO touch_points (
    uid,
    event_slug,
    selection_strategy,
    messages,
    created_at
)
VALUES (?, ?, ?, ?, ?)
        """,
        (
            uid,
            "oseh_302_launch",
            "fixed",
            base64.b85encode(
                gzip.compress(
                    tp.TouchPointMessages.__pydantic_serializer__.to_json(
                        tp.TouchPointMessages(
                            sms=[sms("🎉 Discover What's New: Oseh 3.0.2 {url}")],
                            push=[
                                push(
                                    "🚀 Upgrade Alert: Oseh 3.0.2 Now Available!",
                                    "🌟 Dive into Oseh 3.0.2! Enjoy personalized insights, an improved media player with closed captioning 🎬, and smoother transitions between series.",
                                )
                            ],
                            email=[
                                email(
                                    "Take a minute with Oseh 3.0.2",
                                    "emailOseh302Announcement",
                                )
                            ],
                        )
                    ),
                    compresslevel=9,
                    mtime=0,
                )
            ).decode("ascii"),
            time.time(),
        ),
    )


def sms_uid():
    return f"oseh_tpsms_{secrets.token_urlsafe(16)}"


def sms(fmt: str, *, p=1):
    return tp.TouchPointSmsMessage(
        priority=p, uid=sms_uid(), body_format=fmt, body_parameters=["url"]
    )


def push_uid():
    return f"oseh_tppush_{secrets.token_urlsafe(16)}"


def push(title: str, body: str, *, p=1):
    return tp.TouchPointPushMessage(
        priority=p,
        uid=push_uid(),
        title_format=title,
        title_parameters=[],
        body_format=body,
        body_parameters=[],
        channel_id="daily_reminder",
    )


def email_uid():
    return f"oseh_tpem_{secrets.token_urlsafe(16)}"


def email(subject: str, template: str, *, p=2):
    return tp.TouchPointEmailMessage(
        priority=p,
        uid=email_uid(),
        subject_format=subject,
        subject_parameters=[],
        template=template,
        template_parameters_fixed={},
        template_parameters_substituted=[
            tp.TouchPointTemplateParameterSubstitution(
                key=["unsubscribeUrl"],
                format="{unsubscribe_url}",
                parameters=["unsubscribe_url"],
            ),
        ],
    )
