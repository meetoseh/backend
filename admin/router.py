from fastapi import APIRouter
import admin.routes.read_daily_active_users
import admin.routes.read_daily_phone_verifications
import admin.routes.read_journey_feedback
import admin.routes.read_journey_subcategory_view_stats
import admin.routes.read_journey_views
import admin.routes.read_monthly_active_users
import admin.routes.read_new_users
import admin.routes.read_retention_stats
import admin.routes.read_single_journey_feedback
import admin.routes.read_total_instructors
import admin.routes.read_total_interactive_prompt_sessions
import admin.routes.read_total_journeys
import admin.routes.read_total_users
import admin.routes.read_utm_conversion_stats
import admin.notifs.router
import admin.sms.router
import admin.email.router
import admin.journey_share_links.router
import admin.touch.router
import admin.daily_reminders.router
import admin.siwo.router
import admin.logs.router
import admin.client_flows.router

router = APIRouter()
router.include_router(admin.routes.read_daily_active_users.router)
router.include_router(admin.routes.read_daily_phone_verifications.router)
router.include_router(admin.routes.read_journey_feedback.router)
router.include_router(admin.routes.read_journey_subcategory_view_stats.router)
router.include_router(admin.routes.read_journey_views.router)
router.include_router(admin.routes.read_monthly_active_users.router)
router.include_router(admin.routes.read_new_users.router)
router.include_router(admin.routes.read_retention_stats.router)
router.include_router(admin.routes.read_single_journey_feedback.router)
router.include_router(admin.routes.read_total_instructors.router)
router.include_router(admin.routes.read_total_interactive_prompt_sessions.router)
router.include_router(admin.routes.read_total_journeys.router)
router.include_router(admin.routes.read_total_users.router)
router.include_router(admin.routes.read_utm_conversion_stats.router)

router.include_router(admin.notifs.router.router, prefix="/notifs")
router.include_router(admin.sms.router.router, prefix="/sms")
router.include_router(admin.email.router.router, prefix="/email")
router.include_router(
    admin.journey_share_links.router.router, prefix="/journey_share_links"
)
router.include_router(admin.touch.router.router, prefix="/touch")
router.include_router(admin.daily_reminders.router.router, prefix="/daily_reminders")
router.include_router(admin.siwo.router.router, prefix="/siwo")
router.include_router(admin.logs.router.router, prefix="/logs")
router.include_router(admin.client_flows.router.router, prefix="/client_flows")
