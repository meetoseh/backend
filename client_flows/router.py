from fastapi import APIRouter
import client_flows.routes.create
import client_flows.routes.delete
import client_flows.routes.patch
import client_flows.routes.read
import client_flows.routes.test_flow
import client_flows.routes.test_screen
import client_flows.routes.oneoff_flow

router = APIRouter()
router.include_router(client_flows.routes.create.router)
router.include_router(client_flows.routes.delete.router)
router.include_router(client_flows.routes.patch.router)
router.include_router(client_flows.routes.read.router)
router.include_router(client_flows.routes.test_flow.router)
router.include_router(client_flows.routes.test_screen.router)
router.include_router(client_flows.routes.oneoff_flow.router)
