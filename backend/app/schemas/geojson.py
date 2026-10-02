"""
RFC 7946'nın ihtiyacımız kadarını karşılayan minimal GeoJSON şemaları.

Harita istemcileri (MapLibre/Mapbox) GeoJSON FeatureCollection formatını
doğrudan bir kaynak (source) olarak tüketebildiği için `/spots/bbox` ve
`/spots` (POST) yanıtları bu formatta döner.
"""
import uuid
from typing import Generic, Literal, TypeVar

from pydantic import BaseModel

PropertiesT = TypeVar("PropertiesT", bound=BaseModel)


class PointGeometry(BaseModel):
    type: Literal["Point"] = "Point"
    # GeoJSON spesifikasyonu koordinat sırasını [longitude, latitude]
    # olarak zorunlu kılar - lat/lon SIRASI DEĞİL.
    coordinates: tuple[float, float]


class Feature(BaseModel, Generic[PropertiesT]):
    type: Literal["Feature"] = "Feature"
    id: uuid.UUID
    geometry: PointGeometry
    properties: PropertiesT


class FeatureCollection(BaseModel, Generic[PropertiesT]):
    type: Literal["FeatureCollection"] = "FeatureCollection"
    features: list[Feature[PropertiesT]]
