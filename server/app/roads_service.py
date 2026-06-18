"""
roads_service.py — CRUD for road segments + A* pathfinding over the road graph.

Road types and their travel-speed weights:
  highway : yellow main road    weight_factor = 1.5  (faster)
  road    : gray village road   weight_factor = 1.0
  street  : blue city road      weight_factor = 0.85
"""
from __future__ import annotations

import heapq
import json
import logging
import math
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import DayZMap, RoadSegment

logger = logging.getLogger(__name__)

ROAD_TYPE_SPEED: dict[str, float] = {
    "highway": 1.5,
    "road": 1.0,
    "street": 0.85,
}

# Maximum distance (in map units) to snap a coordinate to the nearest road node
SNAP_DISTANCE = 300.0


# ---------------------------------------------------------------------------
# CRUD helpers
# ---------------------------------------------------------------------------

async def list_segments(db: AsyncSession, map_id: int) -> list[dict]:
    result = await db.execute(
        select(RoadSegment).where(RoadSegment.map_id == map_id).order_by(RoadSegment.id)
    )
    segments = result.scalars().all()
    return [_segment_to_dict(s) for s in segments]


async def create_segment(
    db: AsyncSession, map_id: int, road_type: str, points: list[list[float]]
) -> dict:
    if road_type not in ROAD_TYPE_SPEED:
        road_type = "road"
    seg = RoadSegment(
        map_id=map_id,
        road_type=road_type,
        points=json.dumps(points),
    )
    db.add(seg)
    await db.commit()
    await db.refresh(seg)
    return _segment_to_dict(seg)


async def update_segment(
    db: AsyncSession, segment_id: int, map_id: int,
    road_type: str | None, points: list[list[float]] | None
) -> dict | None:
    result = await db.execute(
        select(RoadSegment).where(RoadSegment.id == segment_id, RoadSegment.map_id == map_id)
    )
    seg = result.scalar_one_or_none()
    if seg is None:
        return None
    if road_type is not None:
        seg.road_type = road_type
    if points is not None:
        seg.points = json.dumps(points)
    await db.commit()
    await db.refresh(seg)
    return _segment_to_dict(seg)


async def delete_segment(db: AsyncSession, segment_id: int, map_id: int) -> bool:
    result = await db.execute(
        select(RoadSegment).where(RoadSegment.id == segment_id, RoadSegment.map_id == map_id)
    )
    seg = result.scalar_one_or_none()
    if seg is None:
        return False
    await db.delete(seg)
    await db.commit()
    return True


async def clear_segments(db: AsyncSession, map_id: int) -> int:
    from sqlalchemy import delete
    result = await db.execute(delete(RoadSegment).where(RoadSegment.map_id == map_id))
    await db.commit()
    return result.rowcount


async def create_segments_bulk(
    db: AsyncSession, map_id: int, segments: list[dict]
) -> list[dict]:
    db_segs = []
    for s in segments:
        road_type = s.get("road_type", "road")
        if road_type not in ROAD_TYPE_SPEED:
            road_type = "road"
        seg = RoadSegment(
            map_id=map_id,
            road_type=road_type,
            points=json.dumps(s.get("points")),
        )
        db.add(seg)
        db_segs.append(seg)
    await db.commit()
    return [_segment_to_dict(s) for s in db_segs]



def _segment_to_dict(seg: RoadSegment) -> dict:
    return {
        "id": seg.id,
        "map_id": seg.map_id,
        "road_type": seg.road_type,
        "points": json.loads(seg.points),
        "created_at": seg.created_at.isoformat() if seg.created_at else None,
    }


# ---------------------------------------------------------------------------
# Graph building
# ---------------------------------------------------------------------------

def _dist(a: tuple[float, float], b: tuple[float, float]) -> float:
    dx = a[0] - b[0]
    dy = a[1] - b[1]
    return math.sqrt(dx * dx + dy * dy)


def build_graph(segments: list[dict]) -> dict[tuple[float, float], list[tuple[float, tuple[float, float]]]]:
    """
    Build adjacency list from road segments.
    Returns: { node: [(cost, neighbour_node), ...] }
    where node = (x, y) float tuple.
    Edge cost = euclidean_distance / speed_factor.
    """
    graph: dict[tuple[float, float], list[tuple[float, tuple[float, float]]]] = {}

    def ensure_node(n):
        if n not in graph:
            graph[n] = []

    for seg in segments:
        pts = seg["points"]
        if len(pts) < 2:
            continue
        speed = ROAD_TYPE_SPEED.get(seg["road_type"], 1.0)
        for i in range(len(pts) - 1):
            a = (float(pts[i][0]), float(pts[i][1]))
            b = (float(pts[i + 1][0]), float(pts[i + 1][1]))
            cost = _dist(a, b) / speed
            ensure_node(a)
            ensure_node(b)
            graph[a].append((cost, b))
            graph[b].append((cost, a))  # bidirectional

    return graph


def nearest_node(
    graph: dict[tuple[float, float], list],
    x: float,
    y: float,
) -> tuple[float, float] | None:
    """Find the closest graph node to the given map coordinate."""
    if not graph:
        return None
    pt = (x, y)
    best = min(graph.keys(), key=lambda n: _dist(n, pt))
    return best


def astar(
    graph: dict[tuple[float, float], list[tuple[float, tuple[float, float]]]],
    start: tuple[float, float],
    goal: tuple[float, float],
) -> list[tuple[float, float]] | None:
    """
    A* algorithm on the road graph.
    Returns list of (x, y) nodes from start to goal, or None if no path found.
    """
    if start not in graph or goal not in graph:
        return None

    # priority queue: (f, g, node)
    open_heap: list[tuple[float, float, tuple[float, float]]] = []
    heapq.heappush(open_heap, (0.0, 0.0, start))

    came_from: dict[tuple[float, float], tuple[float, float] | None] = {start: None}
    g_score: dict[tuple[float, float], float] = {start: 0.0}

    while open_heap:
        f, g, current = heapq.heappop(open_heap)

        if current == goal:
            # reconstruct path
            path: list[tuple[float, float]] = []
            node: tuple[float, float] | None = goal
            while node is not None:
                path.append(node)
                node = came_from[node]
            path.reverse()
            return path

        for edge_cost, neighbour in graph.get(current, []):
            tentative_g = g + edge_cost
            if tentative_g < g_score.get(neighbour, float("inf")):
                g_score[neighbour] = tentative_g
                h = _dist(neighbour, goal)
                heapq.heappush(open_heap, (tentative_g + h, tentative_g, neighbour))
                came_from[neighbour] = current

    return None  # no path found


# ---------------------------------------------------------------------------
# Public navigation entry point
# ---------------------------------------------------------------------------

async def find_route(
    db: AsyncSession,
    game_map: DayZMap,
    from_x: float,
    from_y: float,
    to_x: float,
    to_y: float,
) -> dict[str, Any]:
    """
    Build the road graph from DB and run A* navigation.
    Returns a dict with path, total distance, and snap info.
    """
    segments = await list_segments(db, game_map.id)
    if not segments:
        return {"ok": False, "error": "Дорожная сеть пуста. Добавьте дороги в редакторе."}

    graph = build_graph(segments)
    if not graph:
        return {"ok": False, "error": "Граф дорог пуст."}

    start_node = nearest_node(graph, from_x, from_y)
    goal_node = nearest_node(graph, to_x, to_y)

    if start_node is None or goal_node is None:
        return {"ok": False, "error": "Невозможно найти ближайшую точку дороги."}

    start_snap_dist = _dist(start_node, (from_x, from_y))
    goal_snap_dist = _dist(goal_node, (to_x, to_y))

    if start_snap_dist > SNAP_DISTANCE or goal_snap_dist > SNAP_DISTANCE:
        return {
            "ok": False,
            "error": f"Точка старта или финиша слишком далеко от дороги ({max(start_snap_dist, goal_snap_dist):.0f} ед.). Добавьте дороги рядом с этой точкой.",
        }

    path = astar(graph, start_node, goal_node)
    if path is None:
        return {"ok": False, "error": "Маршрут не найден. Дорожная сеть может быть не связной."}

    # Calculate total distance
    total_dist = 0.0
    for i in range(len(path) - 1):
        total_dist += _dist(path[i], path[i + 1])

    return {
        "ok": True,
        "path": [[p[0], p[1]] for p in path],
        "total_distance": round(total_dist, 1),
        "snap": {
            "start": {"x": start_node[0], "y": start_node[1], "dist": round(start_snap_dist, 1)},
            "goal": {"x": goal_node[0], "y": goal_node[1], "dist": round(goal_snap_dist, 1)},
        },
    }
