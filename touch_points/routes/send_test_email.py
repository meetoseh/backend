from fastapi import APIRouter, Header
from fastapi.responses import Response
from typing import Annotated, Literal, Optional, cast
from touch_points.lib.touch_points import TouchPointEmailMessage
from models import STANDARD_ERRORS_BY_CODE, StandardErrorResponse
from auth import auth_admin
from itgs import Itgs


router = APIRouter()

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
    message: TouchPointEmailMessage,
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

        subject_parameters = dict()
        for key in message.subject_parameters:
            if key.endswith("url"):
                subject_parameters[key] = f"https://oseh.io#{key}"
            elif key == "name":
                subject_parameters[key] = (
                    auth_result.result.claims.get("given_name", "User")
                    if auth_result.result.claims is not None
                    else "User"
                )
            else:
                subject_parameters[key] = "<" + key + ">"
        subject = message.subject_format.format_map(subject_parameters)

        template_parameters = dict()
        stack = [[template_parameters, message.template_parameters_fixed]]
        while stack:
            my_version, to_add = stack.pop()
            for key, value in to_add.items():
                if isinstance(value, dict):
                    my_version[key] = dict()
                    stack.append([my_version[key], value])
                else:
                    my_version[key] = value

        for substitute in message.template_parameters_substituted:
            ele = template_parameters
            for key in substitute.key[:-1]:
                if key not in ele:
                    ele[key] = dict()
                ele = ele[key]

            last_key = substitute.key[-1]
            parameters = dict()
            for parameter in substitute.parameters:
                if parameter == "url":
                    parameters[parameter] = f"https://oseh.io#{parameter}"
                elif parameter == "name":
                    parameters[parameter] = (
                        auth_result.result.claims.get("given_name", "User")
                        if auth_result.result.claims is not None
                        else "User"
                    )
                else:
                    parameters[parameter] = "<" + parameter + ">"
            ele[last_key] = substitute.format.format_map(parameters)

        for email in emails[:3]:
            await jobs.enqueue(
                "runners.emails.send_test",
                email=email,
                subject=subject,
                template=message.template,
                template_parameters=template_parameters,
            )

        return Response(status_code=202)
