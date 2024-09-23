from fastapi import APIRouter
import oauth.silent.routes.begin
import oauth.silent.routes.login
import oauth.silent.routes.merge


router = APIRouter()
router.include_router(oauth.silent.routes.begin.router)
router.include_router(oauth.silent.routes.login.router)
router.include_router(oauth.silent.routes.merge.router)
