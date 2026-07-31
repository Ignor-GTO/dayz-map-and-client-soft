# Server API — события (смерти)

Bridge шлёт события на `POST /api/server/events`. Сервер карты берётся из API-ключа
(`server_id` в теле **не нужен**).

## Auth

```
Authorization: Bearer smk_…
Content-Type: application/json
```

## Endpoint

`POST /api/server/events`

```json
{
  "events": [
    {
      "type": "death",
      "steam_id": "76561198816629288",
      "nickname": "IgnorGTO",
      "profile_id": 8,
      "x": 123456.78,
      "y": -98765.43,
      "z": 1234.5,
      "at": "2026-07-31T09:52:00.123Z"
    }
  ]
}
```

| Поле | Обязательно | Описание |
|------|-------------|----------|
| `type` | да | сейчас только `death` |
| `x`, `y` | да | игровые координаты (не `0,0`) |
| `z` | нет | высота — в маркер и карту высот |
| `steam_id` | желательно | SteamID64 |
| `nickname` | желательно | ник из профиля |
| `profile_id` | нет | SCUM userProfileId |
| `at` | нет | ISO-время смерти |

## Ответ

```json
{
  "ok": true,
  "created": 1,
  "skipped": [
    { "steam_id": "…", "reason": "duplicate" }
  ]
}
```

Причины `skipped`: `unsupported_type`, `invalid_coords`, `zero_coords`, `duplicate`.

Дубликаты: тот же `profile_id` / `steam_id` / ник около тех же координат (±50) за последние 2 минуты.

## Карта

- Маркеры 💀 на веб-карте (фильтр **Смерти (24ч)**).
- Live через WebSocket `{"type":"death","data":{…}}`.
- В `/api/room/state` поле `deaths` — смерти за последние 24 часа.
