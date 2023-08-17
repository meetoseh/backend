import io
from fastapi import APIRouter
from fastapi.requests import Request
from fastapi.responses import Response
import hmac
from error_middleware import handle_contextless_error, handle_error
from itgs import Itgs
from sms.lib.events import MessageResourceEvent, push_message_resource_event
import sms.lib.webhook_stats as webhook_stats
import time
import os
import urllib.parse
import base64

router = APIRouter()


@router.post("/webhook", include_in_schema=False)
async def sms_webhook(request: Request):
    """Twilio webhook endpoint; see also:

    - https://www.twilio.com/docs/usage/webhooks/sms-webhooks
    - https://www.twilio.com/docs/usage/webhooks/webhooks-security
    """
    request_at = time.time()
    async with Itgs() as itgs:
        await webhook_stats.increment_event(itgs, event="received", now=request_at)
        if "x-twilio-signature" not in request.headers:
            await webhook_stats.increment_event(
                itgs, event="signature_missing", now=request_at
            )
            return Response(status_code=401)

        content_type = request.headers.get("content-type")
        if content_type is None:
            await webhook_stats.increment_event(
                itgs, event="body_parse_error", now=request_at
            )
            return Response(status_code=400)

        content_type_parts = [p.strip() for p in content_type.split(";", 2)]
        if content_type_parts[0] != "application/x-www-form-urlencoded":
            await webhook_stats.increment_event(
                itgs, event="body_parse_error", now=request_at
            )
            return Response(status_code=400)

        if len(content_type_parts) not in (1, 2):
            await webhook_stats.increment_event(
                itgs, event="body_parse_error", now=request_at
            )
            return Response(status_code=400)

        hint_parts = [p.strip() for p in content_type_parts[1].split("=", 2)]

        if len(hint_parts) != 2 or hint_parts[0] != "charset":
            await webhook_stats.increment_event(
                itgs, event="body_parse_error", now=request_at
            )
            return Response(status_code=400)

        if hint_parts[1] != "utf-8":
            await webhook_stats.increment_event(
                itgs, event="body_parse_error", now=request_at
            )
            return Response(status_code=400)

        signature_b64: str = request.headers["x-twilio-signature"]
        try:
            signature: bytes = base64.b64decode(signature_b64)
        except:
            await handle_contextless_error(extra_info="signature not b64")
            await webhook_stats.increment_event(
                itgs, event="signature_invalid", now=request_at
            )
            return Response(status_code=403)

        try:
            body_raw = io.BytesIO()
            async for chunk in request.stream():
                if body_raw.tell() + len(chunk) > 1024 * 1024:
                    await webhook_stats.increment_event(
                        itgs, event="body_max_size_exceeded", now=request_at
                    )
                    return Response(status_code=413)
                body_raw.write(chunk)
        except:
            await webhook_stats.increment_event(itgs, event="body_read_error")
            return Response(status_code=500)

        body = body_raw.getvalue()
        if len(body) == 0:
            await handle_contextless_error(extra_info="body empty")
            await webhook_stats.increment_event(
                itgs, event="signature_invalid", now=request_at
            )
            return Response(status_code=403)

        try:
            interpreted_body = urllib.parse.parse_qs(body.decode("utf-8"))
        except:
            await webhook_stats.increment_event(
                itgs, event="body_parse_error", now=request_at
            )
            return Response(status_code=400)

        if any(len(v) != 1 for v in interpreted_body.values()):
            await webhook_stats.increment_event(
                itgs, event="body_parse_error", now=request_at
            )
            return Response(status_code=400)

        api_key = os.environ["OSEH_TWILIO_AUTH_TOKEN"]
        digest = hmac.new(api_key.encode("utf-8"), digestmod="SHA1")
        digest.update(str(request.url).encode("utf-8"))

        for key in sorted(interpreted_body.keys()):
            digest.update(key.encode("utf-8"))
            digest.update(interpreted_body[key][0].encode("utf-8"))

        expected_signature = digest.digest()

        if not hmac.compare_digest(expected_signature, signature):
            await handle_contextless_error(extra_info="signature does not match")
            await webhook_stats.increment_event(
                itgs, event="signature_invalid", now=request_at
            )
            return Response(status_code=403)

        await webhook_stats.increment_event(itgs, event="verified", now=request_at)

        try:
            message_resource_event = MessageResourceEvent.from_webhook(
                interpreted_body, request_at
            )
        except Exception as exc:
            await webhook_stats.increment_event(
                itgs, event="unprocessable", now=request_at
            )
            await handle_error(
                exc, extra_info=f"signature verified; {interpreted_body=}"
            )
            return Response(status_code=200)

        await push_message_resource_event(itgs, message_resource_event)
        await webhook_stats.increment_event(itgs, event="accepted", now=request_at)
        return Response(status_code=200)
