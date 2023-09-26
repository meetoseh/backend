from itgs import Itgs
import secrets
import time
import touch_points.lib.touch_points as tp
import base64
import gzip


async def up(itgs: Itgs) -> None:
    conn = await itgs.conn()
    cursor = conn.cursor()

    uid = f"oseh_tpo_{secrets.token_urlsafe(16)}"
    now = time.time()

    await cursor.execute(
        """
        INSERT INTO touch_points (
            uid, event_slug, selection_strategy, messages, created_at
        )
        VALUES (
            ?, ?, ?, ?, ?
        )
        """,
        (
            uid,
            "daily_reminder",
            "fixed",
            base64.b85encode(
                gzip.compress(
                    tp.TouchPointMessages(
                        # use https://twiliodeved.github.io/message-segment-calculator/ to avoid segmenting
                        sms=[
                            sms(
                                "Good Morning! Let's lift your mood in just 60 seconds. {url}"
                            ),
                            sms(
                                "Hi from Oseh 👋 It’s time for your mindful minute. {url}"
                            ),
                            sms(
                                "Ready to relax? Drop in and choose today's journey. {url}"
                            ),
                            sms("Hi from Oseh 👋 Take your mindful moment today. {url}"),
                            sms(
                                "Hi from Oseh 👋 It’s time to tune in 🧘 – let’s go. {url}"
                            ),
                            sms("You’re 60 seconds away from a clearer mind. {url}"),
                            sms(
                                "Here’s your gentle reminder to take a mindful minute. {url}"
                            ),
                            sms("Hi from Oseh 👋 Change your mood in 60 seconds. {url}"),
                            sms("Hi from Oseh 👋 Stop and take a mindful minute. {url}"),
                            sms(
                                "Ready to relax? Drop in and choose today’s journey. {url}"
                            ),
                            sms("Hi from Oseh 👋 Quiet your mind in 60 seconds. {url}"),
                            sms("Hi from Oseh 👋 Have a minute? {url}"),
                            sms("It's time for today's mindfulness journey. {url}"),
                            sms(
                                "Hi from Oseh! It only takes a minute to change your mindset. {url}"
                            ),
                            sms("Let’s choose your daily dose of mindfulness. {url}"),
                            sms(
                                "😄 Another opportunity for some mindful me-time. {url}"
                            ),
                            sms("Hi from Oseh 👋 Give yourself a minute ⌚ {url}"),
                            sms(
                                "Hi from Oseh! Tune in: {url}. Reply STOP to opt-out.",
                                p=2,
                            ),
                        ],
                        push=[
                            push("Let’s lift your mood in just 60 seconds."),
                            push("It’s time for your mindful minute."),
                            push("Ready to relax? Drop in and choose today's journey."),
                            push("Take your mindful moment today."),
                            push("It’s time to tune in 🧘 – let’s go."),
                            push("You’re 60 seconds away from a clearer mind."),
                            push(
                                "Here’s your gentle reminder to take a mindful minute."
                            ),
                            push("Change your mood in 60 seconds."),
                            push("Stop and take a mindful minute."),
                            push("Ready to relax? Drop in and choose today’s journey."),
                            push("Quiet your mind in 60 seconds."),
                            push("Have a minute?"),
                            push("It's time for today's mindfulness journey."),
                            push("It only takes a minute to change your mindset."),
                            push("Let’s choose your daily dose of mindfulness."),
                            push("Another opportunity for some mindful me-time."),
                            push("Give yourself a minute ⌚"),
                        ],
                        email=[
                            email(
                                "Let’s Keep A Good Thing Going",
                                "It’s time for your mindful minute.",
                                p=1,
                            ),
                            email(
                                "This Will Only Take A Minute",
                                "Let’s lift your mood in just 60 seconds.",
                            ),
                            email(
                                "Ready To Relax?",
                                "Drop in and choose today's journey.",
                            ),
                            email(
                                "It’s Time To Tune In",
                                "You’re 60 seconds away from a clearer mind.",
                            ),
                            email(
                                "Here’s Your Gentle Reminder",
                                "Take your mindful moment today.",
                            ),
                            email(
                                "Take A Minute With Us",
                                "Change your mood in 60 seconds.",
                            ),
                            email(
                                "Small Changes For Lasting Calm",
                                "Quiet your mind in 60 seconds.",
                            ),
                            email(
                                "Your Mindful Minute Awaits",
                                "It's time for today's mindfulness journey.",
                            ),
                            email(
                                "Take A Minute – You Deserve It",
                                "Let’s choose your daily dose of mindfulness.",
                            ),
                            email(
                                "Your Friendly Nudge",
                                "Another opportunity for some mindful me-time.",
                            ),
                            email(
                                "Your Mindful Reminder",
                                "Give yourself a minute ⌚",
                            ),
                            email(
                                "Future You Will Appreciate It",
                                "Take some time to recenter.",
                            ),
                            email(
                                "Take Time To Make Your Soul Happy",
                                "The quieter you are the more you hear",
                            ),
                            email(
                                "A Moment Of Calm", "What you think is what you become"
                            ),
                        ],
                    )
                    .json()
                    .encode("utf-8"),
                    compresslevel=9,
                    mtime=0,
                )
            ).decode("ascii"),
            now,
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


def push(body: str):
    return tp.TouchPointPushMessage(
        priority=1,
        uid=push_uid(),
        title_format="Daily Reminder",
        title_parameters=[],
        body_format=body,
        body_parameters=[],
        channel_id="daily_reminder",
    )


def email_uid():
    return f"oseh_tpem_{secrets.token_urlsafe(16)}"


def email(subject: str, message: str, *, p=2):
    return tp.TouchPointEmailMessage(
        priority=p,
        uid=email_uid(),
        subject_format=subject,
        subject_parameters=[],
        template="dailyReminder",
        template_parameters_fixed={
            "message": message,
        },
        template_parameters_substituted=[
            tp.TouchPointTemplateParameterSubstitution(
                key=["name"], format="{name}", parameters=["name"]
            ),
            tp.TouchPointTemplateParameterSubstitution(
                key=["url"], format="{url}", parameters=["url"]
            ),
            tp.TouchPointTemplateParameterSubstitution(
                key=["unsubscribeUrl"],
                format="{unsubscribe_url}",
                parameters=["unsubscribe_url"],
            ),
        ],
    )
