from datetime import datetime

from pydantic import BaseModel, Field


class LoginRequest(BaseModel):
    pin: str = Field(min_length=4, max_length=16)
    nickname: str = Field(min_length=2, max_length=64)


class LoginResponse(BaseModel):
    nickname: str
    pin: str
    client_key: str | None = None
    message: str


class CoordsPayload(BaseModel):
    x: float
    y: float


class MarkerResponse(BaseModel):
    id: int
    user_id: int
    nickname: str
    x: float
    y: float
    created_at: datetime


class PositionResponse(BaseModel):
    user_id: int
    nickname: str
    x: float
    y: float
    updated_at: datetime


class RoomStateResponse(BaseModel):
    positions: list[PositionResponse]
    markers: list[MarkerResponse]
