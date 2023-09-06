import io
from typing import Callable, Coroutine, Literal, Optional, Union
from urllib.parse import urlparse
from base64 import b64decode
from fastapi import APIRouter, Request
from fastapi.responses import Response, JSONResponse
from starlette.concurrency import run_in_threadpool
from sns.verify_signature import verify_signature
import binascii
import json
import requests
import pem
import inspect
import logging
from itgs import Itgs, our_diskcache as cache
from dataclasses import dataclass

router = APIRouter()


def verify_confirm_subscription(
    body_json: dict, decoded_signature: bytes, signing_certificate: pem.Certificate
) -> Optional[JSONResponse]:
    """Verifies that a request which was signed using the given signature and
    signing certificate whose type is SubscriptionConfirmation has a valid signature
    for the given body and signing certificate.

    If the signature is not valid, returns the appropriate error response.
    Otherwise, returns None.
    """
    verification_error = verify_signature(
        body_json,
        decoded_signature,
        signing_certificate,
        [
            "Message",
            "MessageId",
            "SubscribeURL",
            "Timestamp",
            "Token",
            "TopicArn",
            "Type",
        ],
    )

    if verification_error is not None:
        return JSONResponse(content={"message": verification_error}, status_code=403)

    return None


def verify_notification(
    body_json: dict, decoded_signature: bytes, signing_certificate: pem.Certificate
) -> Optional[JSONResponse]:
    """Like verify_confirm_subscription but for the type Notification"""
    verification_error = verify_signature(
        body_json,
        decoded_signature,
        signing_certificate,
        ["Message", "MessageId", "Subject", "Timestamp", "TopicArn", "Type"],
    )

    if verification_error is not None:
        return JSONResponse(content={"message": verification_error}, status_code=403)

    return None


@dataclass
class SNSResponse:
    request_type: Literal[
        "SignatureMissing",
        "BodyMaxSizeExceeded",
        "BodyParseError",
        "BodyReadError",
        "SignatureInvalid",
        "SubscriptionConfirmation",
        "Notification",
    ]
    """The type of request that was received"""

    response: Response
    """The response that should be returned to the user"""


async def handle_raw_unconfirmed_sns(
    request: Request,
    confirm_subscription: Callable[
        [dict, str], Union[Coroutine[None, None, Response], Response]
    ],
    handle_notification: Callable[
        [dict, str], Union[Coroutine[None, None, Response], Response]
    ],
) -> SNSResponse:
    """This will handle a raw request which was sent to an SNS endpoint. It will
    verify that the message is correctly formatted, has a valid signing certificate
    and signature, and that the signature matches the request and signing certifiate.

    It will then forward the verified request to the handler for the message
    type. If the handlers are defined as `async def` they are executed with
    `await`. Otherwise, they are executed via run_in_threadpool.

    Args:
        request (Request): The request object.
        confirm_subscription (function(body_json, topic_arn) : Coroutine[None, None, Response] or Response):
            A function which we call with the verified body of the request and the
            topic ARN it was sent to. The function MUST make a GET request to the
            SubscribeURL to verify the subscription, and then MUST return the
            appropriate response. Generally use sns.router_utils.std_confirm_subscription
            for the critical parts.
        handle_notification (function(body_json, topic_arn) : Coroutine[None, None, Response] or Response):
            An async function which we call with the verified body of the request and the
            topic ARN it was sent to. The function MUST return the appropriate
            response.

    Returns:
        SNSResponse: The response to return to the client, along with metadata about
            the request.
    """
    message_type = request.headers.get("x-amz-sns-message-type")

    if message_type not in ("SubscriptionConfirmation", "Notification"):
        return SNSResponse(
            request_type="SignatureMissing",
            response=JSONResponse(
                content={"message": f"Unexpected message type: {message_type}"},
                status_code=400,
            ),
        )

    topic_arn = request.headers.get("x-amz-sns-topic-arn")
    if not isinstance(topic_arn, str):
        return SNSResponse(
            request_type="SignatureMissing",
            response=JSONResponse(
                content={"message": "Missing topic ARN"}, status_code=400
            ),
        )

    message_id = request.headers.get("x-amz-sns-message-id")
    if not isinstance(message_id, str):
        return SNSResponse(
            request_type="SignatureMissing",
            response=JSONResponse(
                content={"message": "Missing message ID"}, status_code=400
            ),
        )

    body_bytes = io.BytesIO()
    try:
        async for chunk in request.stream():
            if body_bytes.tell() + len(chunk) > 1024 * 1024:
                return SNSResponse(
                    request_type="BodyMaxSizeExceeded",
                    response=JSONResponse(
                        content={"message": "Body too large (max 1MB)"}, status_code=400
                    ),
                )
            body_bytes.write(chunk)
    except:
        return SNSResponse(
            request_type="BodyReadError",
            response=JSONResponse(
                content={"message": "Failed to read body"}, status_code=400
            ),
        )

    try:
        body_str = str(body_bytes.getvalue(), "utf-8")
    except:
        return SNSResponse(
            request_type="BodyParseError",
            response=JSONResponse(
                content={"message": "Expected utf-8 body"}, status_code=400
            ),
        )

    try:
        body_json = json.loads(body_str)
    except json.decoder.JSONDecodeError:
        return SNSResponse(
            request_type="BodyParseError",
            response=JSONResponse(
                content={"message": "Expected JSON body"}, status_code=400
            ),
        )

    if not isinstance(body_json, dict):
        return SNSResponse(
            request_type="BodyParseError",
            response=JSONResponse(
                content={
                    "message": "Expected a dictionary in the body when interpreted as JSON"
                },
                status_code=400,
            ),
        )

    signature_version = body_json.get("SignatureVersion")
    if signature_version != "1":
        return SNSResponse(
            request_type="BodyParseError",
            response=JSONResponse(
                content={"message": "Unsupported signature version."}, status_code=400
            ),
        )

    signature = body_json.get("Signature")
    if not isinstance(signature, str):
        return SNSResponse(
            request_type="BodyParseError",
            response=JSONResponse(
                content={"message": "Invalid signature (str expected)"}, status_code=401
            ),
        )

    try:
        decoded_signature_bytes = b64decode(signature)
    except binascii.Error:
        return SNSResponse(
            request_type="BodyParseError",
            response=JSONResponse(
                content={
                    "message": "Invalid signature (expected base64-encoded string)"
                },
                status_code=403,
            ),
        )

    signing_cert_url = body_json.get("SigningCertURL")
    if not isinstance(signing_cert_url, str):
        return SNSResponse(
            request_type="BodyParseError",
            response=JSONResponse(
                content={"message": "Invalid signing certificate url (str expected)"},
                status_code=401,
            ),
        )

    parsed_url = urlparse(signing_cert_url)
    if parsed_url.scheme != "https":
        return SNSResponse(
            request_type="BodyParseError",
            response=JSONResponse(
                content={"message": "Only HTTPS signing cert URLs are allowed"},
                status_code=403,
            ),
        )

    if not parsed_url.netloc.endswith(".amazonaws.com"):
        return SNSResponse(
            request_type="BodyParseError",
            response=JSONResponse(
                content={"message": "Unacceptable domain for signing cert URL"},
                status_code=403,
            ),
        )

    if not parsed_url.path.endswith(".pem"):
        return SNSResponse(
            request_type="BodyParseError",
            response=JSONResponse(
                content={"message": "Unacceptable file type for signing cert URL"},
                status_code=403,
            ),
        )

    signing_pem_bytes = cache.get(signing_cert_url)
    if signing_pem_bytes is None:
        response = await run_in_threadpool(
            requests.get, signing_cert_url, allow_redirects=False
        )
        if not response.ok:
            return SNSResponse(
                request_type="SignatureInvalid",
                response=JSONResponse(
                    content={
                        "message": f"Failed to download signing certificate: {response.status_code}"
                    },
                    status_code=403,
                ),
            )

        signing_pem_bytes = response.content

        cache_suggestion = response.headers.get("Content-Cache")
        cache_duration = 600
        if cache_suggestion is not None:
            cache_directives = cache_suggestion.split(",")
            for directive in cache_directives:
                (cmd, val) = directive.split("=")
                cmd = cmd.strip()
                if cmd == "immutable":
                    cache_duration = 604800
                    break
                elif cmd == "max-age":
                    try:
                        cache_duration = min(max(int(val), 5), 604800)
                    except ValueError:
                        pass

        cache.set(signing_cert_url, signing_pem_bytes, expire=cache_duration)

    try:
        certs = pem.parse(signing_pem_bytes)
    except Exception:
        return SNSResponse(
            request_type="SignatureInvalid",
            response=JSONResponse(
                content={
                    "message": "Invalid signing certificate URL (failed to parse)"
                },
                status_code=403,
            ),
        )

    if not certs:
        return SNSResponse(
            request_type="SignatureInvalid",
            response=JSONResponse(
                content={
                    "message": "Invalid signing certificate URL (no certificates found)"
                },
                status_code=403,
            ),
        )

    if not isinstance(certs[0], pem.Certificate):
        return SNSResponse(
            request_type="SignatureInvalid",
            response=JSONResponse(
                content={
                    "message": "Invalid signing certificate URL (expected a certificate)"
                },
                status_code=403,
            ),
        )

    if message_type == "SubscriptionConfirmation":
        verify = verify_confirm_subscription
        fnc = confirm_subscription
    elif message_type == "Notification":
        verify = verify_notification
        fnc = handle_notification
    else:
        # This was checked earlier?
        return SNSResponse(
            request_type="BodyParseError",
            response=JSONResponse(
                status_code=400, content={"message": "Unexpected message type"}
            ),
        )

    if (resp := verify(body_json, decoded_signature_bytes, certs[0])) is not None:
        return SNSResponse(
            request_type="SignatureInvalid",
            response=resp,
        )

    if inspect.iscoroutinefunction(fnc):
        resp = await fnc(body_json, topic_arn=topic_arn)
    else:
        resp = await run_in_threadpool(fnc, body_json, topic_arn=topic_arn)

    return SNSResponse(
        request_type=message_type,
        response=resp,
    )


async def std_confirm_subscription(
    itgs: Itgs, body_json: dict, topic_arn: str
) -> Response:
    """Standard handling of a SubscriptionConfirmation notification via
    auto-confirmation and posting to slack.

    Args:
        itgs (Itgs): the integrations to (re)use
        body_json (dict): The verified and parsed body of the request.
        topic_arn (str): The ARN of the topic.

    Returns:
        Response: The response to return to the client.
    """
    logging.debug(f"Confirming SNS Subscription to {topic_arn}")
    response = await run_in_threadpool(requests.get, body_json["SubscribeURL"])
    if response.ok:
        logging.info(f"Successfully autoconfirmed SNS Subscription to {topic_arn}")
        slack = await itgs.slack()
        await slack.send_ops_message(
            f"Successfully autoconfirmed SNS Subscription to {topic_arn}"
        )
        return JSONResponse(
            content={"message": "Subscription auto-confirmed"}, status_code=200
        )
    else:
        logging.warning(
            f"Failed to autoconfirm SNS Subscription: {response.status_code}"
        )
        logging.warning(response.text)
        slack = await itgs.slack()
        await slack.send_ops_message(
            f"Failed to autoconfirm SNS Subscription to {topic_arn}: {response.status_code}"
        )
        return JSONResponse(
            content={"message": "Failed to confirm subscription"}, status_code=400
        )


async def std_confirm_subscription_wrapper(body_json: dict, topic_arn: str) -> Response:
    """Calls the standard confirm_subscription function with the given arguments
    and a new itgs instance, such that this function signature is valid for
    passing to handle_raw_unconfirmed_sns, which is convenient if you don't
    need to do anything else in the handler.
    """
    async with Itgs() as itgs:
        return await std_confirm_subscription(itgs, body_json, topic_arn)
