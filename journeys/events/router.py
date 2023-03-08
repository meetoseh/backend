from fastapi import APIRouter
import journeys.events.routes.color_prompt_response
import journeys.events.routes.join
import journeys.events.routes.leave
import journeys.events.routes.read
import journeys.events.routes.like
import journeys.events.routes.numeric_prompt_response
import journeys.events.routes.press_prompt_end_response
import journeys.events.routes.press_prompt_start_response
import journeys.events.routes.word_prompt_response


router = APIRouter()
router.include_router(journeys.events.routes.join.router)
router.include_router(journeys.events.routes.leave.router)
router.include_router(journeys.events.routes.like.router)
router.include_router(journeys.events.routes.numeric_prompt_response.router)
router.include_router(journeys.events.routes.press_prompt_start_response.router)
router.include_router(journeys.events.routes.press_prompt_end_response.router)
router.include_router(journeys.events.routes.color_prompt_response.router)
router.include_router(journeys.events.routes.word_prompt_response.router)
router.include_router(journeys.events.routes.read.router)
