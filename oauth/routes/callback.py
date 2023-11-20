from fastapi import APIRouter
from fastapi.responses import RedirectResponse
from typing import Optional
from itgs import Itgs
from urllib.parse import urlencode
import oauth.lib.exchange
from oauth.settings import PROVIDER_TO_SETTINGS
import os

router = APIRouter()


@router.get("/callback", response_class=RedirectResponse, status_code=302)
async def callback(
    state: Optional[str] = None, code: Optional[str] = None, scope: Optional[str] = None
):
    """The standard callback endpoint for the oauth flow. Redirects back to the uri
    specified during the prepare request with the tokens in the url fragment, on
    success, and on failure redirects with auth_error and auth_error_message in
    the query string.
    """
    std_redirect_url = os.environ["ROOT_FRONTEND_URL"]

    if state is None or code is None:
        return RedirectResponse(
            url=f"{std_redirect_url}/?"
            + urlencode(
                {"auth_error": "1", "auth_error_message": "Missing state or code"}
            ),
            status_code=302,
        )

    async with Itgs() as itgs:
        state_info = await oauth.lib.exchange.fetch_state(itgs, state)
        if state_info is None:
            return RedirectResponse(
                url=f"{std_redirect_url}/?"
                + urlencode(
                    {
                        "auth_error": "1",
                        "auth_error_message": "Invalid, expired, or already used state",
                    }
                ),
                status_code=302,
            )

        if state_info.provider not in ("Google", "Direct"):
            return RedirectResponse(
                url=f"{state_info.redirect_uri}/?"
                + urlencode(
                    {
                        "auth_error": "1",
                        "auth_error_message": "Invalid provider for this callback",
                    }
                ),
                status_code=302,
            )

        if state_info.merging_with_user_sub is not None:
            merge_info = await oauth.lib.exchange.use_standard_merge_exchange(
                itgs, code, PROVIDER_TO_SETTINGS[state_info.provider], state_info
            )
            return RedirectResponse(
                url=f"{state_info.redirect_uri}/#"
                + urlencode(
                    {
                        "merge_token": merge_info.merge_jwt,
                    }
                )
            )

        response = await oauth.lib.exchange.use_standard_exchange(
            itgs, code, PROVIDER_TO_SETTINGS[state_info.provider], state_info
        )

        return RedirectResponse(
            url=f"{state_info.redirect_uri}/#"
            + urlencode(
                {
                    "id_token": response.id_token,
                    **(
                        {"refresh_token": response.refresh_token}
                        if response.refresh_token is not None
                        else {}
                    ),
                    **({"onboard": "1"} if response.onboard else {}),
                }
            )
        )
