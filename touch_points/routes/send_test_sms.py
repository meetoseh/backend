from fastapi import APIRouter, Header
from fastapi.responses import Response
from typing import Annotated, Literal, Optional, cast
from touch_points.lib.create_preview_parameters import create_preview_parameters
from touch_points.lib.touch_points import TouchPointSmsMessage
from models import STANDARD_ERRORS_BY_CODE, StandardErrorResponse
from auth import auth_admin
from itgs import Itgs


router = APIRouter()

ERROR_404_TYPES = Literal["no_phone"]
ERROR_NO_PHONE_RESPONSE = Response(
    content=StandardErrorResponse[ERROR_404_TYPES](
        type="no_phone",
        message="You do not have a verified phone number to send the test to",
    ).model_dump_json(),
    headers={"Content-Type": "application/json; charset=utf-8"},
    status_code=404,
)


@router.post("/send_test_sms", status_code=202, responses=STANDARD_ERRORS_BY_CODE)
async def send_touch_point_test_sms(
    message: TouchPointSmsMessage,
    authorization: Annotated[Optional[str], Header()] = None,
):
    """Sends a test SMS message to the verified phone numbers for the authorized
    user. This accepts a message from the `sms` list of a touch point, though it
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
            "SELECT phone_number FROM users, user_phone_numbers "
            "WHERE"
            " users.sub = ?"
            " AND user_phone_numbers.user_id = users.id"
            " AND user_phone_numbers.verified",
            (auth_result.result.sub,),
        )
        if not response.results:
            return ERROR_NO_PHONE_RESPONSE

        phone_numbers = [cast(str, row[0]) for row in response.results]
        jobs = await itgs.jobs()

        parameters = await create_preview_parameters(
            itgs,
            user_sub=auth_result.result.sub,
            requested=set(message.body_parameters),
        )
        if "url" in parameters:
            parameters["url"] = "oseh.io/a/1234"
        body = message.body_format.format_map(parameters)

        for phone_number in phone_numbers[:3]:
            await jobs.enqueue(
                "runners.sms.send_test", phone_number=phone_number, body=body
            )

        return Response(status_code=202)
