from typing import Dict
from fastapi import APIRouter, Request, UploadFile
from fastapi.responses import Response
from fastapi import APIRouter
from error_middleware import handle_error
from twilio.request_validator import RequestValidator as TwilioRequestValidator
import os
from itgs import Itgs
from loguru import logger


router = APIRouter()


@router.post("/twilio/callback")
async def twilio_callback(oseh_uid: str, request: Request):
    try:
        params = await request.form()
    except Exception as e:
        await handle_error(e)
        return Response(status_code=400)

    # if they attempted to upload any files, we reject the request
    for key, value in params.items():
        if isinstance(value, UploadFile):
            await params.close()
            return Response(status_code=400)

    # if they repeated any keys, we reject the request
    if len(params.multi_items()) != len(params):
        await params.close()
        return Response(status_code=400)

    # alright; this can be treated as a standard dictionary
    raw_params: Dict[str, str] = dict(params.multi_items())
    await params.close()

    twilio_signature = request.headers.get("X-Twilio-Signature")
    validator = TwilioRequestValidator(os.environ["OSEH_TWILIO_AUTH_TOKEN"])

    uri = str(request.url)
    if not validator.validate(uri, raw_params, twilio_signature):
        logger.error(f"Twilio callback signature validation failed for {uri=}")
        return Response(status_code=401)

    expected_account_sid = os.environ["OSEH_TWILIO_ACCOUNT_SID"]
    if params.get("AccountSid") != expected_account_sid:
        logger.error(
            f"Twilio callback AccountSid {params.get('AccountSid')=} does not match expected {expected_account_sid=}"
        )
        return Response(status_code=200)

    return await handle_validated_twilio_callback(oseh_uid, raw_params)


async def handle_validated_twilio_callback(oseh_uid: str, params: Dict[str, str]):
    """Handles a twilio webhook that we have confirmed actually came from
    twilio. The parameters are the form data that was sent with the request.

    The oseh_uid is specified by us when we form the URL that twilio calls,
    and is used to identify the user_notification that this callback is for.
    """
    new_status = params.get("MessageStatus")
    if new_status is None:
        logger.error(
            f"Twilio callback {oseh_uid=}, {params=} did not contain MessageStatus"
        )
        return Response(status_code=200)

    async with Itgs() as itgs:
        conn = await itgs.conn()
        cursor = conn.cursor("weak")

        response = await cursor.execute(
            "UPDATE user_notifications SET status=? WHERE uid=?",
            (new_status, oseh_uid),
        )

        if response.rows_affected is None or response.rows_affected < 1:
            logger.warning(
                f"Twilio callback {oseh_uid=}, {params=} did not update any rows"
            )

        return Response(status_code=200)
