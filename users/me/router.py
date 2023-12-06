from fastapi import APIRouter
import users.me.routes.cancel_subscription
import users.me.routes.delete_account
import users.me.routes.finish_checkout_stripe
import users.me.routes.like_journey
import users.me.routes.picture
import users.me.routes.read_course_journeys
import users.me.routes.read_daily_reminder_settings
import users.me.routes.read_daily_reminders
import users.me.routes.read_entitlements
import users.me.routes.read_history
import users.me.routes.read_identities
import users.me.routes.read_merge_account_suggestions
import users.me.routes.read_revenue_cat_id
import users.me.routes.read_streak
import users.me.routes.read_wants_notif_time_prompt
import users.me.routes.set_goal
import users.me.routes.start_ai_journey
import users.me.routes.start_checkout_stripe
import users.me.routes.start_introductory_journey
import users.me.routes.start_journey_from_history
import users.me.routes.started_ai_journey
import users.me.routes.unlike_journey
import users.me.routes.unsubscribe_daily_reminders
import users.me.routes.update_name
import users.me.routes.update_notification_time
import users.me.routes.update_timezone
import users.me.routes.upload_profile_picture
import users.me.interests.router

router = APIRouter()

router.include_router(users.me.routes.cancel_subscription.router)
router.include_router(users.me.routes.delete_account.router)
router.include_router(users.me.routes.picture.router)
router.include_router(users.me.routes.read_course_journeys.router)
router.include_router(
    users.me.routes.read_daily_reminder_settings.router, tags=["notifications"]
)
router.include_router(
    users.me.routes.read_daily_reminders.router, tags=["notifications"]
)
router.include_router(users.me.routes.read_entitlements.router)
router.include_router(users.me.routes.read_history.router)
router.include_router(users.me.routes.read_identities.router)
router.include_router(users.me.routes.read_merge_account_suggestions.router)
router.include_router(users.me.routes.read_revenue_cat_id.router)
router.include_router(users.me.routes.read_streak.router)
router.include_router(users.me.routes.read_wants_notif_time_prompt.router)
router.include_router(users.me.routes.set_goal.router)
router.include_router(users.me.routes.start_ai_journey.router)
router.include_router(users.me.routes.start_checkout_stripe.router)
router.include_router(users.me.routes.finish_checkout_stripe.router)
router.include_router(users.me.routes.like_journey.router)
router.include_router(users.me.routes.start_introductory_journey.router)
router.include_router(users.me.routes.start_journey_from_history.router)
router.include_router(users.me.routes.started_ai_journey.router)
router.include_router(users.me.routes.unlike_journey.router)
router.include_router(
    users.me.routes.unsubscribe_daily_reminders.router, tags=["notifications"]
)
router.include_router(users.me.routes.update_name.router)
router.include_router(users.me.routes.update_notification_time.router)
router.include_router(users.me.routes.update_timezone.router)
router.include_router(users.me.routes.upload_profile_picture.router)

router.include_router(users.me.interests.router.router, prefix="/interests")
