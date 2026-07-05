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
    # Optional password required to enter the room (in addition to PIN).
    entry_password_hash: Mapped[str | None] = mapped_column(String(128), nullable=True)
    # First user who created/joined the room; may manage room settings.
    created_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    map: Mapped["DayZMap"] = relationship(back_populates="rooms")
    users: Mapped[list["User"]] = relationship(
        back_populates="room",
        cascade="all, delete-orphan",
        foreign_keys="User.room_id",
    )
    creator: Mapped["User | None"] = relationship(
        foreign_keys=[created_by_user_id],
    )


class User(Base):
    __tablename__ = "users"
    __table_args__ = (UniqueConstraint("room_id", "nickname", name="uq_room_nickname"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    room_id: Mapped[int] = mapped_column(ForeignKey("rooms.id"), index=True)
    nickname: Mapped[str] = mapped_column(String(64))
    client_key_hash: Mapped[str] = mapped_column(String(128))
    # Optional password to protect nickname from impersonation within a PIN group.
    profile_password_hash: Mapped[str | None] = mapped_column(String(128), nullable=True)
    avatar_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    # user | vip | moderator | admin — privileges on the live map
    role: Mapped[str] = mapped_column(String(16), default="user", server_default="user")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    room: Mapped["Room"] = relationship(
        back_populates="users",
        foreign_keys=[room_id],
    )
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
    marker_category: Mapped[str] = mapped_column(String(16), default="group", server_default="group")
    title: Mapped[str | None] = mapped_column(String(128), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    image_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    geometry_kind: Mapped[str] = mapped_column(String(16), default="point", server_default="point")
    points_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    radius: Mapped[float | None] = mapped_column(Float, nullable=True)
    stroke_color: Mapped[str | None] = mapped_column(String(16), nullable=True)
    fill_color: Mapped[str | None] = mapped_column(String(16), nullable=True)
    # Server stashes (marker_category=stash) are tied to map, visible to all PIN groups.
    map_id: Mapped[int | None] = mapped_column(ForeignKey("dayz_maps.id"), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    user: Mapped["User"] = relationship(back_populates="markers")


class Trader(Base):
    __tablename__ = "traders"
    __table_args__ = (UniqueConstraint("map_id", "name", name="uq_trader_map_name"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    map_id: Mapped[int] = mapped_column(ForeignKey("dayz_maps.id"), index=True)
    name: Mapped[str] = mapped_column(String(128), index=True)
    x: Mapped[float | None] = mapped_column(Float, nullable=True)
    y: Mapped[float | None] = mapped_column(Float, nullable=True)
    # Optional link to a server marker (MapPoi) whose coordinates define this trader's location.
    poi_id: Mapped[int | None] = mapped_column(ForeignKey("map_pois.id"), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    sections: Mapped[list["TraderSection"]] = relationship(
        back_populates="trader",
        cascade="all, delete-orphan",
    )


class TraderSection(Base):
    __tablename__ = "trader_sections"
    __table_args__ = (UniqueConstraint("trader_id", "name", name="uq_trader_section_name"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    trader_id: Mapped[int] = mapped_column(ForeignKey("traders.id"), index=True)
    name: Mapped[str] = mapped_column(String(128), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    trader: Mapped["Trader"] = relationship(back_populates="sections")
    subsections: Mapped[list["TraderSubsection"]] = relationship(
        back_populates="section",
        cascade="all, delete-orphan",
    )


class TraderSubsection(Base):
    __tablename__ = "trader_subsections"
    __table_args__ = (UniqueConstraint("section_id", "name", name="uq_trader_subsection_name"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    section_id: Mapped[int] = mapped_column(ForeignKey("trader_sections.id"), index=True)
    name: Mapped[str] = mapped_column(String(128), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    section: Mapped["TraderSection"] = relationship(back_populates="subsections")
    items: Mapped[list["TraderItem"]] = relationship(
        back_populates="subsection",
        cascade="all, delete-orphan",
    )


class TraderItem(Base):
    __tablename__ = "trader_items"
    __table_args__ = (UniqueConstraint("subsection_id", "name", name="uq_trader_item_name"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    subsection_id: Mapped[int] = mapped_column(ForeignKey("trader_subsections.id"), index=True)
    name: Mapped[str] = mapped_column(String(160), index=True)
    buy_price: Mapped[int] = mapped_column(Integer, default=0)
    sell_price: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    subsection: Mapped["TraderSubsection"] = relationship(back_populates="items")


class AdminAccount(Base):
    __tablename__ = "admin_accounts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    login: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(128))
    # admin — full panel access; moderator — panel without account management
    role: Mapped[str] = mapped_column(String(16), default="admin", server_default="admin")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
