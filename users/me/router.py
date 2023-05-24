from fastapi import APIRouter
import users.me.routes.cancel_subscription
import users.me.routes.delete_account
import users.me.routes.finish_checkout_stripe
import users.me.routes.picture
import users.me.routes.read_entitlements
import users.me.routes.read_revenue_cat_id
import users.me.routes.read_streak
import users.me.routes.read_wants_notif_time_prompt
import users.me.routes.set_goal
import users.me.routes.start_ai_journey
import users.me.routes.start_checkout_stripe
import users.me.routes.start_introductory_journey
import users.me.routes.update_name
import users.me.routes.update_notification_time
import users.me.routes.update_timezone
import users.me.routes.upload_profile_picture

router = APIRouter()

router.include_router(users.me.routes.cancel_subscription.router)
router.include_router(users.me.routes.delete_account.router)
router.include_router(users.me.routes.picture.router)
router.include_router(users.me.routes.read_entitlements.router)
router.include_router(users.me.routes.read_revenue_cat_id.router)
router.include_router(users.me.routes.read_streak.router)
router.include_router(users.me.routes.read_wants_notif_time_prompt.router)
router.include_router(users.me.routes.set_goal.router)
router.include_router(users.me.routes.start_ai_journey.router)
router.include_router(users.me.routes.start_checkout_stripe.router)
router.include_router(users.me.routes.finish_checkout_stripe.router)
router.include_router(users.me.routes.start_introductory_journey.router)
router.include_router(users.me.routes.update_name.router)
router.include_router(users.me.routes.update_notification_time.router)
router.include_router(users.me.routes.update_timezone.router)
router.include_router(users.me.routes.upload_profile_picture.router)
