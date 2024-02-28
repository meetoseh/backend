from fastapi import APIRouter, Header
from fastapi.responses import Response
from auth import auth_any
from itgs import Itgs
from models import STANDARD_ERRORS_BY_CODE, StandardErrorResponse
from typing import Annotated, Literal, Optional
from users.lib.prices import get_localized_price, PurchasesStoreProduct


router = APIRouter()


ERROR_404_TYPES = Literal["product_not_found"]
ERROR_PRODUCT_NOT_FOUND_RESPONSE = Response(
    content=StandardErrorResponse[ERROR_404_TYPES](
        type="product_not_found", message="There is no stripe product with the given id"
    ).model_dump_json(),
    headers={"Content-Type": "application/json; charset=utf-8"},
    status_code=404,
)


@router.get(
    "/stripe/products/{product_id}/price",
    response_model=PurchasesStoreProduct,
    responses={
        "404": {
            "description": "The product with the given id was not found",
            "model": StandardErrorResponse[ERROR_404_TYPES],
        },
        **STANDARD_ERRORS_BY_CODE,
    },
)
async def read_stripe_price(
    product_id: str, authorization: Annotated[Optional[str], Header()] = None
):
    """Determines the localized price associated with the stripe product with the
    given ID for the authorized user.

    Typically, `read_offerings` is used to get what offers are available to
    the user, and then those are sent to the app store to determine
    the localized price. For stripe, there is no app store, and hence this
    endpoint can be used instead.

    We will change product ids if we change the price, and so the result is cacheable
    so long as the users locale doesn't change.
    """
    async with Itgs() as itgs:
        auth_result = await auth_any(itgs, authorization)
        if auth_result.result is None:
            return auth_result.error_response

        price = await get_localized_price(
            itgs,
            user_sub=auth_result.result.sub,
            platform_product_identifier=product_id,
            platform="stripe",
        )
        if price is None:
            return ERROR_PRODUCT_NOT_FOUND_RESPONSE

        return Response(
            content=price.__pydantic_serializer__.to_json(price),
            headers={
                "Content-Type": "application/json; charset=utf-8",
                "Cache-Control": "private, max-age=3600, stale-while-revalidate=3600, stale-if-error=86400",
            },
            status_code=200,
        )
