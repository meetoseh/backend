from fastapi import APIRouter
import users.me.screens.routes.peek
import users.me.screens.routes.pop
import users.me.screens.routes.trace

import users.me.screens.routes.pop_to_series
import users.me.screens.routes.pop_to_series_class
import users.me.screens.routes.pop_to_emotion_class
import users.me.screens.routes.pop_to_history_class
import users.me.screens.routes.pop_to_phone_verify

import users.me.screens.routes.empty_with_merge_token
import users.me.screens.routes.empty_with_confirm_merge

router = APIRouter()
router.include_router(users.me.screens.routes.peek.router)
router.include_router(users.me.screens.routes.pop.router)
router.include_router(users.me.screens.routes.trace.router)

router.include_router(users.me.screens.routes.pop_to_series.router)
router.include_router(users.me.screens.routes.pop_to_series_class.router)
router.include_router(users.me.screens.routes.pop_to_emotion_class.router)
router.include_router(users.me.screens.routes.pop_to_history_class.router)
router.include_router(users.me.screens.routes.pop_to_phone_verify.router)

router.include_router(users.me.screens.routes.empty_with_merge_token.router)
router.include_router(users.me.screens.routes.empty_with_confirm_merge.router)
