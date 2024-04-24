from fastapi import APIRouter, Header
from fastapi.responses import Response
from typing import Annotated, Literal, Optional, cast
from touch_points.lib.touch_points import TouchPointPushMessage
from models import STANDARD_ERRORS_BY_CODE, StandardErrorResponse
from auth import auth_admin
from itgs import Itgs


router = APIRouter()

ERROR_404_TYPES = Literal["no_token"]
ERROR_NO_TOKEN_RESPONSE = Response(
    content=StandardErrorResponse[ERROR_404_TYPES](
        type="no_token",
        message="You do not have a push token to send the test to",
    ).model_dump_json(),
    headers={"Content-Type": "application/json; charset=utf-8"},
    status_code=404,
)


@router.post("/send_test_push", status_code=202, responses=STANDARD_ERRORS_BY_CODE)
async def send_touch_point_test_push(
    message: TouchPointPushMessage,
    authorization: Annotated[Optional[str], Header()] = None,
):
    """Sends a test push message to the push tokens for the authorized
    user. This accepts a message from the `push` list of a touch point, though it
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
            "SELECT token FROM users, user_push_tokens "
            "WHERE"
            " users.sub = ?"
            " AND user_push_tokens.user_id = users.id",
            (auth_result.result.sub,),
        )
        if not response.results:
            return ERROR_NO_TOKEN_RESPONSE

        tokens = [cast(str, row[0]) for row in response.results]
        jobs = await itgs.jobs()

        parameters = dict()
        for key in set(message.body_parameters + message.title_parameters):
            if key == "name":
                parameters[key] = (
                    auth_result.result.claims.get("given_name", "User")
                    if auth_result.result.claims is not None
                    else "User"
                )
            else:
                parameters[key] = "<" + key + ">"
        body = message.body_format.format_map(parameters)
        title = message.title_format.format_map(parameters)

        for push_token in tokens[:10]:
            await jobs.enqueue(
                "runners.push.send_test",
                push_token=push_token,
                title=title,
                body=body,
                channel_id=message.channel_id,
            )

        return Response(status_code=202)
