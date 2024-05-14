from fastapi import APIRouter
import admin.client_flows.content.routes.create
import admin.client_flows.content.routes.read

router = APIRouter()

router.include_router(admin.client_flows.content.routes.create.router)
router.include_router(admin.client_flows.content.routes.read.router)
