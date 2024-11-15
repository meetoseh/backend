from fastapi import APIRouter
import personalization.routes.find_combinations
import personalization.routes.find_lowest_view_counts
import personalization.routes.find_feedback_score
import personalization.routes.find_adjusted_scores
import personalization.routes.find_best_categories
import personalization.routes.find_best_journeys
import personalization.routes.analyze

import personalization.home.router

router = APIRouter()
router.include_router(personalization.routes.find_combinations.router)
router.include_router(personalization.routes.find_lowest_view_counts.router)
router.include_router(personalization.routes.find_feedback_score.router)
router.include_router(personalization.routes.find_adjusted_scores.router)
router.include_router(personalization.routes.find_best_categories.router)
router.include_router(personalization.routes.find_best_journeys.router)
router.include_router(personalization.routes.analyze.router)

router.include_router(personalization.home.router.router, prefix="/home")
