"""v1 API'nin tüm alt router'larını tek çatı altında toplar."""
from fastapi import APIRouter

from app.api.v1.endpoints import (
    auth,
    field_verifications,
    lists,
    live_reports,
    spot_interactions,
    spots,
    users,
    vehicle_profiles,
)

api_router = APIRouter()
api_router.include_router(auth.router)
from app.api.v1.endpoints import search

api_router.include_router(search.router)
api_router.include_router(spots.router)
api_router.include_router(spot_interactions.router)
api_router.include_router(field_verifications.router)
api_router.include_router(live_reports.spot_router)
api_router.include_router(live_reports.report_router)
api_router.include_router(live_reports.moderation_router)
api_router.include_router(users.router)
api_router.include_router(lists.router)
api_router.include_router(vehicle_profiles.router)

from app.api.v1.endpoints import content_reports

api_router.include_router(content_reports.router)

