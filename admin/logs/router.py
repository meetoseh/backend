from fastapi import APIRouter

import admin.logs.routes.read_contact_method_log
import admin.logs.routes.read_daily_reminder_settings_log
import admin.logs.routes.read_user_client_screen_actions_log
import admin.logs.routes.read_user_client_screens_log

router = APIRouter()
router.include_router(admin.logs.routes.read_contact_method_log.router)
router.include_router(admin.logs.routes.read_daily_reminder_settings_log.router)
router.include_router(admin.logs.routes.read_user_client_screen_actions_log.router)
router.include_router(admin.logs.routes.read_user_client_screens_log.router)
