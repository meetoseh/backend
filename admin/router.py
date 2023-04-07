from fastapi import APIRouter
import admin.routes.read_daily_active_users
import admin.routes.read_daily_phone_verifications
import admin.routes.read_journey_feedback
import admin.routes.read_journey_subcategory_view_stats
import admin.routes.read_journey_views
import admin.routes.read_monthly_active_users
import admin.routes.read_new_users
import admin.routes.read_retention_stats
import admin.routes.read_total_instructors
import admin.routes.read_total_interactive_prompt_sessions
import admin.routes.read_total_journeys
import admin.routes.read_total_user_notification_settings
import admin.routes.read_total_users
import admin.routes.read_utm_conversion_stats

router = APIRouter()
router.include_router(admin.routes.read_daily_active_users.router)
router.include_router(admin.routes.read_daily_phone_verifications.router)
router.include_router(admin.routes.read_journey_feedback.router)
router.include_router(admin.routes.read_journey_subcategory_view_stats.router)
router.include_router(admin.routes.read_journey_views.router)
router.include_router(admin.routes.read_monthly_active_users.router)
router.include_router(admin.routes.read_new_users.router)
router.include_router(admin.routes.read_retention_stats.router)
router.include_router(admin.routes.read_total_instructors.router)
router.include_router(admin.routes.read_total_interactive_prompt_sessions.router)
router.include_router(admin.routes.read_total_journeys.router)
router.include_router(admin.routes.read_total_user_notification_settings.router)
router.include_router(admin.routes.read_total_users.router)
router.include_router(admin.routes.read_utm_conversion_stats.router)
