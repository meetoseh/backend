from fastapi import APIRouter
import admin.daily_reminders.routes.daily_reminder_stats
import admin.daily_reminders.routes.read_last_assign_time_job
import admin.daily_reminders.routes.read_last_send_job
import admin.daily_reminders.routes.read_progress_info
import admin.daily_reminders.routes.read_queued_info

router = APIRouter()
router.include_router(admin.daily_reminders.routes.daily_reminder_stats.router)
router.include_router(admin.daily_reminders.routes.read_last_assign_time_job.router)
router.include_router(admin.daily_reminders.routes.read_last_send_job.router)
router.include_router(admin.daily_reminders.routes.read_progress_info.router)
router.include_router(admin.daily_reminders.routes.read_queued_info.router)
