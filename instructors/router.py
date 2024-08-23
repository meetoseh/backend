from fastapi import APIRouter
import instructors.routes.create_picture
import instructors.routes.create
import instructors.routes.read_public
import instructors.routes.read
import instructors.routes.update

router = APIRouter()
router.include_router(instructors.routes.create_picture.router)
router.include_router(instructors.routes.create.router)
router.include_router(instructors.routes.read_public.router)
router.include_router(instructors.routes.read.router)
router.include_router(instructors.routes.update.router)
