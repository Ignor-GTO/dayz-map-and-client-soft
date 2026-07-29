# Server API — позиции с игрового сервера SCUM

Клиент (exe) остаётся для **zoom / focus**. Позиции можно слать с хоста SCUM.

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
      "steam_id": "76561198011111111",
      "nickname": "ShadowWolf",
      "x": -145230.0,
      "y": 87420.0,
      "z": 12300.5
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

Сопоставление: `steam_id` → иначе `nickname`, только среди пользователей карты ключа (и PIN-группы, если ключ ограничен).

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
  -d "{\"players\":[{\"steam_id\":\"76561198011111111\",\"x\":-145230,\"y\":87420}]}"
```

## Настройка игроков

Админка → **Пользователи** → колонка **SteamID64** → Сохранить.
