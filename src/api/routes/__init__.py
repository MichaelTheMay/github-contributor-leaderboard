from fastapi import APIRouter

from src.api.routes.contributors import router as contributors_router
from src.api.routes.dashboard import router as dashboard_router
from src.api.routes.jobs import router as jobs_router
from src.api.routes.leaderboard import router as leaderboard_router
from src.api.routes.repositories import router as repositories_router
from src.api.routes.scoring import router as scoring_router

router = APIRouter()

router.include_router(repositories_router, prefix="/repositories", tags=["repositories"])
router.include_router(leaderboard_router, prefix="/leaderboard", tags=["leaderboard"])
router.include_router(contributors_router, prefix="/contributors", tags=["contributors"])
router.include_router(scoring_router, prefix="/config", tags=["configuration"])
router.include_router(jobs_router, prefix="/jobs", tags=["jobs"])
router.include_router(dashboard_router, prefix="/dashboard", tags=["dashboard"])
