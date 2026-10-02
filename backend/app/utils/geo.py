"""
PostGIS (WKBElement) <-> düz lat/lon dönüşüm yardımcıları.

`spots.coordinates` sütunu SQLAlchemy tarafında GeoAlchemy2 WKBElement
olarak; Pydantic/GeoJSON tarafında ise (longitude, latitude) çifti
olarak temsil edilir. Bütün dönüşümler tek noktadan buradan geçer.
"""
from geoalchemy2.shape import from_shape, to_shape
from geoalchemy2.types import WKBElement
from shapely.geometry import Point


def wkb_to_lonlat(point: WKBElement) -> tuple[float, float]:
    """WKBElement -> (longitude, latitude)."""
    shapely_point = to_shape(point)
    return shapely_point.x, shapely_point.y


def lonlat_to_wkb(longitude: float, latitude: float) -> WKBElement:
    """(longitude, latitude) -> SRID 4326 WKBElement (spots.coordinates için)."""
    return from_shape(Point(longitude, latitude), srid=4326)
