from fastapi import APIRouter
import referral.routes.create_user_daily_event_invite
import referral.routes.redeem_user_daily_event_invite


router = APIRouter()
router.include_router(referral.routes.create_user_daily_event_invite.router)
router.include_router(referral.routes.redeem_user_daily_event_invite.router)
