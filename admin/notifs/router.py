from fastapi import APIRouter
import admin.notifs.routes.read_daily_push_tokens
import admin.notifs.routes.read_todays_push_token_stats
import admin.notifs.routes.read_total_push_tokens

router = APIRouter()
router.include_router(admin.notifs.routes.read_daily_push_tokens.router)
router.include_router(admin.notifs.routes.read_todays_push_token_stats.router)
router.include_router(admin.notifs.routes.read_total_push_tokens.router)
