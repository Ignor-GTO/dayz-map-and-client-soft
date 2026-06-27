from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class DayZMap(Base):
    __tablename__ = "dayz_maps"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    slug: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(128))
    map_size: Mapped[float] = mapped_column(Float, default=20480)
    tiles_satellite: Mapped[str] = mapped_column(Text)
    tiles_topographic: Mapped[str] = mapped_column(Text)
    max_native_zoom: Mapped[int] = mapped_column(Integer, default=7)
    extra_zoom: Mapped[int] = mapped_column(Integer, default=3)
    locations_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    locations_source: Mapped[str | None] = mapped_column(String(16), nullable=True)
    radiation_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    rooms: Mapped[list["Room"]] = relationship(back_populates="map")
    pois: Mapped[list["MapPoi"]] = relationship(back_populates="map", cascade="all, delete-orphan")
    road_segments: Mapped[list["RoadSegment"]] = relationship(back_populates="map", cascade="all, delete-orphan")


class RoadSegment(Base):
    """A single polyline segment of a road on the map."""
    __tablename__ = "road_segments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    map_id: Mapped[int] = mapped_column(ForeignKey("dayz_maps.id"), index=True)
    # highway = yellow main road, road = gray village road, street = blue city road
    road_type: Mapped[str] = mapped_column(String(32), default="road")
    # JSON-encoded list of [x, y] pairs: [[x1,y1],[x2,y2],...]
    points: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    map: Mapped["DayZMap"] = relationship(back_populates="road_segments")


class MapPoi(Base):
    __tablename__ = "map_pois"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    map_id: Mapped[int] = mapped_column(ForeignKey("dayz_maps.id"), index=True)
    title: Mapped[str] = mapped_column(String(128))
    description: Mapped[str] = mapped_column(Text, default="")
    description_image_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    icon: Mapped[str] = mapped_column(String(32), default="star")
    x: Mapped[float] = mapped_column(Float)
    y: Mapped[float] = mapped_column(Float)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    map: Mapped["DayZMap"] = relationship(back_populates="pois")


class Setting(Base):
    __tablename__ = "settings"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[str] = mapped_column(Text)


class Room(Base):
    __tablename__ = "rooms"
    __table_args__ = (UniqueConstraint("map_id", "pin", name="uq_map_pin"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    map_id: Mapped[int] = mapped_column(ForeignKey("dayz_maps.id"), index=True)
    pin: Mapped[str] = mapped_column(String(16), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    map: Mapped["DayZMap"] = relationship(back_populates="rooms")
    users: Mapped[list["User"]] = relationship(back_populates="room", cascade="all, delete-orphan")


class User(Base):
    __tablename__ = "users"
    __table_args__ = (UniqueConstraint("room_id", "nickname", name="uq_room_nickname"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    room_id: Mapped[int] = mapped_column(ForeignKey("rooms.id"), index=True)
    nickname: Mapped[str] = mapped_column(String(64))
    client_key_hash: Mapped[str] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    room: Mapped["Room"] = relationship(back_populates="users")
    position: Mapped["Position | None"] = relationship(
        back_populates="user", uselist=False, cascade="all, delete-orphan"
    )
    markers: Mapped[list["Marker"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )


class Position(Base):
    __tablename__ = "positions"

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), primary_key=True)
    x: Mapped[float] = mapped_column(Float)
    y: Mapped[float] = mapped_column(Float)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    user: Mapped["User"] = relationship(back_populates="position")


class Marker(Base):
    __tablename__ = "markers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    x: Mapped[float] = mapped_column(Float)
    y: Mapped[float] = mapped_column(Float)
    type: Mapped[str] = mapped_column(String(32), default="marker", server_default="marker")
    title: Mapped[str | None] = mapped_column(String(128), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    image_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    user: Mapped["User"] = relationship(back_populates="markers")
