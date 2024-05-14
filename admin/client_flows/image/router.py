from fastapi import APIRouter
import admin.client_flows.image.routes.create
import admin.client_flows.image.routes.read

router = APIRouter()
router.include_router(admin.client_flows.image.routes.create.router)
router.include_router(admin.client_flows.image.routes.read.router)
