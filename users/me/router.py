from fastapi import APIRouter
import users.me.routes.picture

router = APIRouter()

router.include_router(users.me.routes.picture.router)
