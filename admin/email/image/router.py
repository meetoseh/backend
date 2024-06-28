from fastapi import APIRouter
import admin.email.image.routes.create
import admin.email.image.routes.read

router = APIRouter()

router.include_router(admin.email.image.routes.create.router)
router.include_router(admin.email.image.routes.read.router)
