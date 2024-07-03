import json
import os
from fastapi import APIRouter, Header
from fastapi.responses import Response
from typing import Annotated, Any, Literal, Optional, cast
from pydantic import BaseModel, Field
from touch_points.lib.schema.check_touch_point_schema import make_template_parameters
from touch_points.lib.touch_points import TouchPointEmailMessage
from models import STANDARD_ERRORS_BY_CODE, StandardErrorResponse
from auth import auth_admin
from emails.auth import create_jwt as create_email_jwt
from itgs import Itgs
import aiohttp


router = APIRouter()


class SendTestEmailRequest(BaseModel):
    event_parameters: Any = Field(description="The parameters to use for the event")
    message: TouchPointEmailMessage = Field(
        description="The message to send, formatted with the given event parameters"
    )


ERROR_404_TYPES = Literal["no_email"]
ERROR_NO_EMAIL_RESPONSE = Response(
    content=StandardErrorResponse[ERROR_404_TYPES](
        type="no_email",
        message="You do not have a verified email to send the test to",
    ).model_dump_json(),
    headers={"Content-Type": "application/json; charset=utf-8"},
    status_code=404,
)


@router.post("/send_test_email", status_code=202, responses=STANDARD_ERRORS_BY_CODE)
async def send_touch_point_test_email(
    args: SendTestEmailRequest,
    authorization: Annotated[Optional[str], Header()] = None,
):
    """Sends a test email message to the verified email addresses for the authorized
    user. This accepts a message from the `email` list of a touch point, though it
    ignores the uid and priority (ie., it is stateless with respect to touch_points)

    Requires standard authorization for an admin user.
    """
    async with Itgs() as itgs:
        auth_result = await auth_admin(itgs, authorization)
        if auth_result.result is None:
            return auth_result.error_response

        conn = await itgs.conn()
        cursor = conn.cursor("none")
        response = await cursor.execute(
            "SELECT email FROM users, user_email_addresses "
            "WHERE"
            " users.sub = ?"
            " AND user_email_addresses.user_id = users.id"
            " AND user_email_addresses.verified",
            (auth_result.result.sub,),
        )
        if not response.results:
            return ERROR_NO_EMAIL_RESPONSE

        emails = [cast(str, row[0]) for row in response.results]
        jobs = await itgs.jobs()

        subject = args.message.subject_format.format_map(args.event_parameters)

        template_parameters = make_template_parameters(
            event_parameters=args.event_parameters,
            template_parameters_fixed=args.message.template_parameters_fixed,
            template_parameters_substituted=args.message.template_parameters_substituted,
        )

        # before sending the test, verify we shouldn't get a templating error..
        email_template_jwt = await create_email_jwt(
            itgs, args.message.template, duration=60
        )
        root_email_template_url = os.environ["ROOT_EMAIL_TEMPLATE_URL"]
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{root_email_template_url}/api/3/templates/{args.message.template}",
                headers={
                    "Authorization": f"Bearer {email_template_jwt}",
                    "Content-Type": "application/json; charset=utf-8",
                    "Accept": "text/html; charset=utf-8",
                },
                data=json.dumps(template_parameters).encode("utf-8"),
            ) as resp:
                if not resp.ok:
                    slack = await itgs.slack()
                    text = await resp.text()
                    await slack.send_web_error_message(
                        f"Test email failed! Failed to template {args.message.template} using parameters:\n\n```\n{json.dumps(template_parameters, indent=2)}\n```\n\nResponse:\n\n```\n{text}\n```\n\nStatus: {resp.status}"
                    )
                    return Response(
                        content=text.encode("utf-8"),
                        headers={"Content-Type": resp.headers["Content-Type"]},
                        status_code=resp.status,
                    )

        for email in emails[:3]:
            await jobs.enqueue(
                "runners.emails.send_test",
                email=email,
                subject=subject,
                template=args.message.template,
                template_parameters=template_parameters,
            )

        return Response(status_code=202)
