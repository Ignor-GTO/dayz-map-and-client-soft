# DayZ Map — GTO Team

Live-карта для DayZ с группами по PIN-коду, веб-интерфейсом и Windows-клиентом для автоматической отправки координат с экрана (iZurvive / браузерная карта).

**Продакшен:** https://dayz-map.gto-team.uz  
**Репозиторий:** https://github.com/Ignor-GTO/dayz-map-and-client-soft  
**Клиент (exe):** [GitHub Releases — DayZ Map Client](https://github.com/Ignor-GTO/dayz-map-and-client-soft/releases/tag/client-latest)

---

## Возможности

### Веб-карта
- Несколько карт (сейчас по умолчанию **Припять / Pripyat Gamma**)
- Группы игроков по **PIN-коду** — у каждой группы своя «комната» на карте
- Live-позиции участников через WebSocket
- Метки на карте (в т.ч. со скриншота через клиент)
- Подписи локаций в стиле iZurvive (города, военные, водоёмы и т.д.) с фильтрами
- Спутник / топографическая подложка (тайлы Xam.nu)
- POI-метки, настраиваемые в админке

### Windows-клиент (`DayZMapClient.exe`)
- GUI на tkinter, без консоли
- **OCR координат** с экрана — Windows OCR или встроенный RapidOCR (работает без языковых пакетов Windows)
- Настройка монитора и области захвата с **живым редактором** рамки
- Пресет **iZurvive** для полоски `15100 / 879` внизу слева
- Перед захватом по **M** — сдвиг мыши на **левую панель** iZurvive (координаты игрока, а не курсора на карте)
- Hotkeys:
  - **M** — отправить текущую позицию на сервер
  - **Win+Shift+S** — метка с координат со скриншота в буфере обмена

### Админ-панель (`/admin.html`)
- Управление картами, тайлами, URL локаций
- POI-метки
- PIN-группы (комнаты) по картам
- Политика PIN: публичное создание групп или только через админа
- Смена пароля администратора

---

## Архитектура

```
┌─────────────────┐     HTTPS/WS      ┌──────────────────────────────┐
│ DayZMapClient   │ ────────────────► │ FastAPI + SQLite + WebSocket │
│ (Windows OCR)   │   position/marker │  static/ (Leaflet map UI)    │
└─────────────────┘                   └──────────────────────────────┘
         │                                        │
         │ OCR с монитора                         │ браузер
         ▼                                        ▼
   iZurvive / карта в браузере              Игроки в одной PIN-группе
```

| Компонент | Стек |
|-----------|------|
| Сервер | Python 3.11, FastAPI, SQLAlchemy, SQLite, WebSocket |
| Фронтенд | Leaflet, vanilla JS |
| Клиент | Python 3.11+, tkinter, mss, winrt / RapidOCR, PyInstaller |
| Деплой | Docker Compose, Dokploy |

---

## Быстрый старт (игрок)

1. Откройте https://dayz-map.gto-team.uz
2. Выберите карту, введите **PIN группы** и **никнейм**
3. Сохраните **ключ клиента** — показывается один раз при первом входе
4. Скачайте [DayZMapClient.exe](https://github.com/Ignor-GTO/dayz-map-and-client-soft/releases/tag/client-latest)
5. В клиенте укажите URL сервера и ключ → **Сохранить**
6. Настройте OCR (см. ниже) → **Запустить hotkeys**
7. В игре откройте iZurvive, нажимайте **M** для live-позиции

---

## Настройка Windows-клиента

### Монитор
- В выпадающем списке выберите монитор с картой iZurvive
- Основной монитор помечен **«· основной»**
- Кнопка **↻** обновляет список

### Область OCR (iZurvive)
Координаты игрока отображаются внизу слева: `My X/Y: 15100 / 879`.

1. Нажмите **iZurvive** — подставит область `210, 915, 330, 945` (только цифры, 1920×1080)
2. **Редактор области** — перетащите рамку на полоску координат
3. **Тест OCR (M)** — проверка распознавания (в логе будет сырой текст OCR)

> Если карта на другом разрешении или масштабе — подгоните L, T, R, B вручную.

### Сдвиг мыши перед M
На iZurvive:
- курсор **на карте** → показываются координаты под курсором;
- курсор **на левой панели** → `My X/Y` — координаты **игрока**.

Включите галочку **«Перед M сдвигать мышь на левую панель»** (рекомендуется).

### OCR-движки
| Движок | Когда используется |
|--------|-------------------|
| **Windows OCR** | Если установлен языковой пакет «Оптическое распознавание символов» |
| **Встроенный RapidOCR** | Автоматически, если Windows OCR недоступен |

Установка Windows OCR (опционально, для скорости):
1. Параметры → Время и язык → Язык и регион
2. Русский → Языковые параметры → **Оптическое распознавание символов** → Скачать

Или кнопка **Установить Windows OCR** в клиенте (PowerShell от администратора).

### config.json
Рядом с `DayZMapClient.exe` создаётся `config.json`:

```json
{
  "server_url": "https://dayz-map.gto-team.uz",
  "client_key": "ваш-ключ",
  "monitor_index": 1,
  "ocr_region": [210, 915, 330, 945],
  "mouse_nudge_before_ocr": true,
  "mouse_nudge_side": "left",
  "mouse_nudge_delay_ms": 350,
  "mouse_nudge_restore": true
}
```

Пример: `client/config.json.example`

---

## Админ-панель

URL: `/admin.html`  
Пароль по умолчанию: `9029902901` (смените после первого входа).

| Раздел | Описание |
|--------|----------|
| Карты | slug, название, размер, тайлы, URL локаций (iZurvive / xam.nu) |
| POI | Статические метки на карте |
| PIN-группы | Создание комнат с PIN для каждой карты |
| Настройки | Публичное создание PIN при логине вкл/выкл |

---

## API (основное)

| Метод | Путь | Описание |
|-------|------|----------|
| GET | `/api/health` | Проверка живости |
| GET | `/api/maps` | Список карт |
| GET | `/api/maps/{slug}/config` | Конфиг карты (тайлы, bounds) |
| GET | `/api/maps/{slug}/locations` | Локации для подписей на карте |
| GET | `/api/auth/pin-policy` | Можно ли создавать новые PIN при логине |
| POST | `/api/auth/login` | Вход (PIN + никнейм + map_slug) |
| POST | `/api/client/position` | Позиция (Bearer: ключ клиента) |
| POST | `/api/client/marker` | Метка (Bearer: ключ клиента) |
| WS | `/ws/map` | Live-обновления комнаты |

Админ: префикс `/api/admin/…`

---

## Локальная разработка

### Сервер

```bash
cd server
python -m venv .venv
.venv\Scripts\activate          # Windows
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

Откройте http://127.0.0.1:8000

Переменные окружения — см. `.env.example` и `server/app/config.py`.

### Клиент

```bash
cd client
pip install -r requirements.txt
python main.py
```

### Сборка exe

```bash
cd client
pip install -r requirements.txt
pyinstaller build.spec --noconfirm
# Результат: client/dist/DayZMapClient.exe
```

При push в `main` (изменения в `client/`) GitHub Actions собирает exe и публикует в [Releases](https://github.com/Ignor-GTO/dayz-map-and-client-soft/releases/tag/client-latest). Версия автоматически увеличивается (`client/VERSION`).

---

## Деплой (Docker / Dokploy)

### Docker Compose

```bash
cp .env.example .env   # заполните SECRET_KEY
docker compose up -d --build
```

Сервис слушает порт **8000**. Данные SQLite — volume `dayz_map_data` → `/data`.

### Dokploy

Скрипт первичного развёртывания: `scripts/deploy-dokploy.ps1`  
Compose id (пример): `9IFMxcg0UXYbFLIAS_1A7`

После push в `main` с изменениями сервера — **Redeploy** compose в панели Dokploy.

### Переменные окружения

| Переменная | Описание | По умолчанию |
|------------|----------|--------------|
| `SECRET_KEY` | Секрет сессий (обязательно в проде) | — |
| `SERVER_PUBLIC_URL` | Публичный URL сервера | `https://dayz-map.gto-team.uz` |
| `DEFAULT_ADMIN_PASSWORD` | Пароль админа при первом seed | `9029902901` |
| `MAP_SIZE` | Размер карты (метры) | `20480` |
| `MAP_TILES_SATELLITE` | URL тайлов спутника | Xam.nu Pripyat |
| `MAP_TILES_TOPOGRAPHIC` | URL топо-тайлов | Xam.nu Pripyat |
| `CLIENT_DOWNLOAD_URL` | Ссылка на скачивание exe | GitHub Releases |
| `DATA_DIR` | Каталог БД | `/data` |

---

## Структура репозитория

```
dayz_map_and_client_soft/
├── client/                 # Windows GUI + OCR
│   ├── main.py
│   ├── gui_app.py
│   ├── ocr_engine.py       # Windows OCR + fallback
│   ├── capture.py          # мониторы, скриншот области
│   ├── mouse_util.py       # сдвиг мыши на панель iZurvive
│   ├── region_overlay.py   # редактор OCR-области
│   ├── build.spec          # PyInstaller
│   └── VERSION
├── server/
│   ├── app/                # FastAPI backend
│   │   ├── routes.py
│   │   ├── admin_routes.py
│   │   ├── locations_service.py
│   │   └── seed.py
│   └── static/             # index.html, map.js, admin
├── docker-compose.yml
├── .github/workflows/        # build-client.yml
└── scripts/deploy-dokploy.ps1
```

---

## Решение проблем

### На карте нет подписей локаций (404 `/api/maps/.../locations`)
Сервер не обновлён. Пересоберите и задеплойте Docker-образ на Dokploy.

### Клиент: «координаты не распознаны»
1. Проверьте область OCR (кнопка **iZurvive** + редактор)
2. Включите сдвиг мыши на левую панель
3. **Проверка OCR** — должен работать встроенный или Windows OCR
4. Убедитесь, что iZurvive показывает `My X/Y: … / …` в выбранной области

### Клиент: ошибка `winrt.windows.foundation.collections`
Скачайте свежий exe из GitHub Releases (старые сборки без полного winrt).

### Карта Leaflet пустая / серые клетки
Обновите страницу (Ctrl+F5). Тайлы загружаются с `static.xam.nu` — нужен интернет.

### PIN не создаётся при входе
Админ отключил публичное создание PIN — попросите PIN у администратора или создайте группу в `/admin.html`.

### Мониторы перепутаны в клиенте
Используйте **↻** и выберите монитор с пометкой «основной» или тот, где открыта карта.

---

## Лицензия и атрибуция

- Тайлы карт: [Xam.nu](https://xam.nu) / DayZavr
- Логика координат локаций: [dzmap](https://github.com/WoozyMasta/dzmap), данные iZurvive / xam.nu
- Проект GTO Team — внутреннее использование

---

## Контакты

Вопросы и баги — Issues в GitHub или команда GTO Team.
