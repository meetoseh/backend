from fastapi import APIRouter
import users.me.interests.routes.read_my_interests
import users.me.interests.routes.set_my_interests

router = APIRouter()
router.include_router(users.me.interests.routes.read_my_interests.router)
router.include_router(users.me.interests.routes.set_my_interests.router)
