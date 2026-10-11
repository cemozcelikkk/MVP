"""
Tüm ORM modellerini tek noktadan içe aktarır.

Alembic'in `target_metadata = Base.metadata` üzerinden tüm tabloları
görebilmesi için bu modül `env.py` içinde import edilecektir.
"""
from app.core.database import Base
from app.models.basemap_poi import BasemapPoi
from app.models.check_in import CheckIn
from app.models.dynamic_status import DynamicStatus
from app.models.field_verification import SpotFieldVerification
from app.models.live_report_event import LiveReportEvent
from app.models.osm_cache import OsmPoi, OsmTile
from app.models.review import Review
from app.models.saved_list import SavedList, SavedListItem
from app.models.service_point import (
    ServicePoint,
    ServicePointConfirmation,
    ServicePointReport,
    ServicePointReview,
    ServicePointStatusUpdate,
)
from app.models.spot import Spot
from app.models.spot_amenities import SpotAmenities
from app.models.spot_passability import SpotPassability
from app.models.spot_photo import SpotPhoto
from app.models.user import User
from app.models.vehicle_profile import VehicleProfile

__all__ = [
    "ContentReport",
    "SpotChange",
    "AccountToken",
    "RequestQuota",
    "PlaceCache",
    "Base",
    "BasemapPoi",
    "Spot",
    "SpotPassability",
    "SpotAmenities",
    "DynamicStatus",
    "Review",
    "SpotPhoto",
    "CheckIn",
    "User",
    "SavedList",
    "SavedListItem",
    "ServicePoint",
    "ServicePointConfirmation",
    "ServicePointReport",
    "ServicePointReview",
    "ServicePointStatusUpdate",
    "VehicleProfile",
    "SpotFieldVerification",
    "LiveReportEvent",
    "OsmPoi",
    "OsmTile",
]

from app.models.account_token import AccountToken, PlaceCache, RequestQuota
from app.models.content_report import ContentReport, SpotChange
