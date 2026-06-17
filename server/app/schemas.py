from datetime import datetime

from pydantic import BaseModel, Field


class LoginRequest(BaseModel):
    map_slug: str = Field(min_length=2, max_length=64)
    pin: str = Field(min_length=4, max_length=16)
    nickname: str = Field(min_length=2, max_length=64)


class LoginResponse(BaseModel):
    nickname: str
    pin: str
    map_slug: str
    map_name: str
    client_key: str | None = None
    message: str


class CoordsPayload(BaseModel):
    x: float
    y: float
    type: str | None = None


class MarkerResponse(BaseModel):
    id: int
    user_id: int
    nickname: str
    x: float
    y: float
    type: str = "marker"
    created_at: datetime


class PoiResponse(BaseModel):
    id: int
    title: str
    description: str
    description_image_url: str | None = None
    icon: str = "star"
    x: float
    y: float


class PositionResponse(BaseModel):
    user_id: int
    nickname: str
    x: float
    y: float
    updated_at: datetime


class RoomStateResponse(BaseModel):
    map_slug: str
    map_name: str
    positions: list[PositionResponse]
    markers: list[MarkerResponse]
    pois: list[PoiResponse]


class MapListItem(BaseModel):
    slug: str
    name: str


class MapConfigResponse(BaseModel):
    slug: str
    name: str
    bounds: dict
    map_size: float
    max_native_zoom: int
    extra_zoom: int
    tiles_satellite: str
    tiles_topographic: str
    attribution: str
    server_url: str
    client_download_url: str


class MapLocationItem(BaseModel):
    title: str
    category: str
    type: str
    label_class: str
    x: float
    y: float
    min_zoom: int = 4


class LocationCategory(BaseModel):
    id: str
    label: str
    count: int


class MapLocationsResponse(BaseModel):
    categories: list[LocationCategory]
    locations: list[MapLocationItem]


class RadiationBounds(BaseModel):
    x1: float
    y1: float
    x2: float
    y2: float


class RadiationOverlay(BaseModel):
    url: str
    enabled: bool = False
    opacity: float = 0.3
    bounds: RadiationBounds


class RadiationZone(BaseModel):
    id: str = ""
    label: str = ""
    x: float
    y: float
    radius: float
    color: str = "#ff9800"
    fillOpacity: float = 0.18
    strokeOpacity: float = 0.9
    weight: int = 2


class RadiationPolygon(BaseModel):
    id: str = ""
    tier: str = ""
    label: str = ""
    color: str = "#ff9800"
    fillOpacity: float = 0.4
    strokeOpacity: float = 0.95
    weight: int = 2
    rings: list[list[list[float]]]


class RadiationLegendItem(BaseModel):
    color: str
    label: str


class MapRadiationResponse(BaseModel):
    overlay: RadiationOverlay | None = None
    polygons: list[RadiationPolygon] = []
    zones: list[RadiationZone] = []
    legend: list[RadiationLegendItem] = []


class AdminLoginRequest(BaseModel):
    password: str


class AdminPasswordRequest(BaseModel):
    current_password: str
    new_password: str = Field(min_length=6, max_length=128)


class AdminPinPolicyRequest(BaseModel):
    public_pin_creation: bool


class AdminPinCreateRequest(BaseModel):
    map_slug: str = Field(min_length=2, max_length=64)
    pin: str = Field(min_length=4, max_length=16)


class MapCreateRequest(BaseModel):
    slug: str = Field(min_length=2, max_length=64)
    name: str = Field(min_length=2, max_length=128)
    map_size: float = 20480
    tiles_satellite: str
    tiles_topographic: str
    max_native_zoom: int = 7
    extra_zoom: int = 3
    locations_url: str = ""
    locations_source: str = "izurvive"
    radiation_url: str = ""
    enabled: bool = True
    sort_order: int = 0


class MapUpdateRequest(BaseModel):
    name: str | None = None
    map_size: float | None = None
    tiles_satellite: str | None = None
    tiles_topographic: str | None = None
    max_native_zoom: int | None = None
    extra_zoom: int | None = None
    locations_url: str | None = None
    locations_source: str | None = None
    radiation_url: str | None = None
    enabled: bool | None = None
    sort_order: int | None = None


class PoiCreateRequest(BaseModel):
    map_slug: str
    title: str = Field(min_length=1, max_length=128)
    description: str = ""
    icon: str = "star"
    x: float
    y: float


class PoiUpdateRequest(BaseModel):
    title: str | None = None
    description: str | None = None
    icon: str | None = None
    x: float | None = None
    y: float | None = None


class RadiationBoundsInput(BaseModel):
    x1: float = 0
    y1: float = 0
    x2: float = 20480
    y2: float = 20480


class RadiationOverlayInput(BaseModel):
    url: str = ""
    opacity: float = 0.65
    bounds: RadiationBoundsInput = RadiationBoundsInput()
    editorOnly: bool = True


class RadiationSaveRequest(BaseModel):
    map_slug: str
    zones: list[RadiationZone]
    legend: list[RadiationLegendItem] = []
    overlay: RadiationOverlayInput | None = None
