# Server API — позиции с игрового сервера SCUM

Клиент (exe) остаётся для **zoom / focus**. Позиции можно слать с хоста SCUM
(bridge / RCON-агент). Сервер карты определяется по API-ключу
(`SCUM_MAP_SERVER_ID` только в env bridge — **в теле не передаётся**).

## Auth

```
Authorization: Bearer smk_…
```

или заголовок `X-Api-Key: smk_…`

Ключ создаётся в админке → вкладка **Server API** (или `python -m app.create_server_api_key`).

## Endpoint

`POST /api/server/positions`

```json
{
  "players": [
    {
      "steam_id": "76561198816629288",
      "nickname": "IgnorGTO",
      "x": 575144.6875,
      "y": -220808.8125,
      "z": 669.9,
      "travel_mode": "foot",
      "vehicle_role": null,
      "vehicle_type": null
    }
  ]
}
```

| Поле | Обязательно | Описание |
|------|-------------|----------|
| `x`, `y` | да | мировые координаты SCUM (см) |
| `z` | нет | игнорируется |
| `steam_id` | желательно | SteamID64 — основной матч с пользователем карты |
| `nickname` | запасной | ник персонажа на карте (без учёта регистра) |
| `travel_mode` | нет | `foot` \| `vehicle` |
| `vehicle_role` | нет | `driver` \| `passenger` (при `vehicle`) |
| `vehicle_type` | нет | класс техники, напр. `RIS`, `SUV_01`, `WheelBarrow_Metal` |

Сопоставление: `steam_id` → иначе `nickname`, только среди пользователей карты ключа (и PIN-группы, если ключ ограничен).

### Примеры

**Водитель**

```json
{
  "players": [
    {
      "steam_id": "76561198816629288",
      "nickname": "IgnorGTO",
      "x": 412000.5,
      "y": -198000.25,
      "z": 120.0,
      "travel_mode": "vehicle",
      "vehicle_role": "driver",
      "vehicle_type": "RIS"
    }
  ]
}
```

**Пассажир**

```json
{
  "players": [
    {
      "steam_id": "76561198816629288",
      "nickname": "IgnorGTO",
      "x": 412000.5,
      "y": -198000.25,
      "z": 120.0,
      "travel_mode": "vehicle",
      "vehicle_role": "passenger",
      "vehicle_type": "WheelBarrow_Metal"
    }
  ]
}
```

## Ответ

```json
{
  "ok": true,
  "updated": 1,
  "skipped": [
    { "steam_id": "7656…", "nickname": null, "reason": "user_not_found" }
  ]
}
```

## Пример curl

```bash
curl -X POST "https://YOUR_HOST/api/server/positions" \
  -H "Authorization: Bearer smk_…" \
  -H "Content-Type: application/json" \
  -d "{\"players\":[{\"steam_id\":\"76561198011111111\",\"x\":-145230,\"y\":87420,\"travel_mode\":\"foot\"}]}"
```

## Настройка игроков

1. **Авто (рекомендуется):** ScumMapClient сам читает SteamID64 с ПК и шлёт `POST /api/client/steam-id`.
2. **Вручную:** Админка → Пользователи → колонка SteamID64 → Сохранить.
