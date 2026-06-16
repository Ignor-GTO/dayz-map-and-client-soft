# ТЕХНИЧЕСКОЕ ЗАДАНИЕ (ТЗ) И ИСХОДНЫЙ КОД
## Разработка легального OCR-парсера координат и локального модуля кастомного маппинга для DayZ (Карта: Припять)

---

## 1. НАЗНАЧЕНИЕ И ЦЕЛИ СИСТЕМЫ
Цель проекта — создание автономного программного комплекса для ориентирования на кастомном сервере DayZavr (Сервер №2, Припять ATOMCORE) без вмешательства в память игры и обхода античита BattlEye.

### Основные задачи:
1. **Автоматизация считывания координат**: Исключить ручной ввод цифр с внутриигрового GPS-экрана.
2. **Отображение скрытых объектов**: Извлечь и визуализировать кастомные постройки, дороги и точки интереса, которые добавлены администрацией сервера, но отсутствуют на официальном сайте.
3. **Безопасность аккаунта**: Работа строго в режиме чтения экрана (Read-Only Screen OCR) для исключения рисков получения HWID-бана.

---

## 2. ТЕХНИЧЕСКИЕ ТРЕБОВАНИЯ К ОКРУЖЕНИЮ
* **Язык разработки**: Python 3.10+
* **Операционная система**: Windows 10 / 11
* **Стороннее ПО**: Tesseract OCR (движок оптического распознавания).
* **Зависимости Python**: `pillow`, `keyboard`, `pytesseract`, `matplotlib`.

### Инструкция по развертыванию:
1. Скачать и установить [Tesseract OCR для Windows](https://github.com). По умолчанию установить в: `C:\Program Files\Tesseract-OCR`.
2. Установить библиотеки через терминал:
   ```bash
   pip install pillow keyboard pytesseract matplotlib
   ```

---

## 3. АРХИТЕКТУРА И ЭТАПЫ РАБОТЫ С ДАННЫМИ

### Схема работы комплекса:
Используйте код с осторожностью.[Игра DayZ (Экран GPS)] ──(Клавиша M)──> [Python OCR Скрипт] ──> [Извлечение X и Y]│[Файлы сервера .pbo] ──(PBO Manager)──> [custom_buildings.json] ───────┼──> [Отрисовка карты]│[Файлы картинки] ─────────────────────> [pripyat.png] ──────────────────┘
### Этап 1: Получение гео-данных сервера (Сбор маппинга)
1. Перейти в каталог модов: `...\Steam\steamapps\common\DayZ\!Workshop\`
2. Найти целевую папку: **`@Server2_PripyatGamma`**.
3. Из подпапки `Addons` скопировать `.pbo` файлы, содержащие в названии `map`, `mapping` или `server`.
4. Распаковать их через утилиту **PBO Manager** и извлечь координаты строений (перевести в формат `custom_buildings.json`).

---

## 4. ИСХОДНЫЙ КОД МОДУЛЕЙ

Вы можете использовать систему в двух режимах на выбор.

### ВАРИАНТ А. Автоматическое открытие официального сайта DayZavr
*Используется, если вам не нужно выводить свои скрытые здания, а достаточно быстро открыть браузер на нужной точке.*

```python
import os
import re
import webbrowser
import keyboard
import pytesseract
from PIL import ImageGrab

# Конфигурация пути к OCR движку
pytesseract.pytesseract.tesseract_cmd = r"C:\Program Files\Tesseract-OCR\tesseract.exe"

def get_coordinates_online():
    print("[OCR] Считывание экрана...")

    # Координаты левого нижнего угла экрана (настройка под 1080p монитор)
    left, top, right, bottom = 10, 900, 300, 1050

    # Захват кадра и оптимизация под чтение текста (Черно-белый фильтр)
    screen_zone = ImageGrab.grab(bbox=(left, top, right, bottom)).convert("L")

    # Распознавание символов
    text = pytesseract.image_to_string(
        screen_zone, 
        config="--psm 6 --oem 3 -c tessedit_char_whitelist=0123456789.,"
    )
    numbers = re.findall(r'\d+', text)

    if len(numbers) >= 2:
        x_coord, y_coord = numbers[0], numbers[1]
        print(f"[Успех] Координаты найдены: X={x_coord}, Y={y_coord}")

        # Формирование URL для интерактивной карты DayZavr Припять
        map_url = f"https://dayzavr.ru{x_coord}&y={y_coord}"
        webbrowser.open(map_url)
    else:
        print("[Ошибка] Цифры не найдены. Проверьте положение GPS-интерфейса в игре.")

print("[Запуск] Скрипт активен. Нажмите 'M' в игре...")
keyboard.add_hotkey('m', get_coordinates_online)
keyboard.wait()
```

---

### ВАРИАНТ Б. Автономная карта с кастомными зданиями и дорогами
*Используется для полной независимости от сайта. Скрипт берет картинку карты Припяти, наносит туда здания из файла сервера и ставит крестик на вашей позиции.*

```python
import os
import re
import json
import keyboard
import pytesseract
import matplotlib.pyplot as plt
import matplotlib.image as mpimg
from PIL import ImageGrab

pytesseract.pytesseract.tesseract_cmd = r"C:\Program Files\Tesseract-OCR\tesseract.exe"

# Настройки ресурсов
MAP_IMAGE = "pripyat.png"              # Файл изображения карты в папке скрипта
BUILDINGS_JSON = "custom_buildings.json"  # Распакованный маппинг из .pbo

def render_local_map(player_x, player_y):
    if not os.path.exists(MAP_IMAGE):
        print(f"[Ошибка] Отсутствует файл карты: {MAP_IMAGE}")
        return

    # 1. Отрисовка подложки карты
    img = mpimg.imread(MAP_IMAGE)
    fig, ax = plt.subplots(figsize=(12, 12))
    ax.imshow(img)

    # 2. Нанесение кастомных объектов сервера из JSON
    if os.path.exists(BUILDINGS_JSON):
        try:
            with open(BUILDINGS_JSON, "r", encoding="utf-8") as f:
                data = json.load(f)
            
            x_buildings, z_buildings = [], []
            for obj in data:
                if "Position" in obj:
                    pos = obj["Position"]
                    # В DayZ: pos[0] = X, pos[1] = Высота, pos[2] = Z (Север-Юг на 2D карте)
                    x_buildings.append(pos[0])
                    z_buildings.append(pos[2])

            # Рисуем все скрытые постройки синими маркерами
            ax.scatter(x_buildings, z_buildings, c='blue', s=8, label='Объекты сервера', alpha=0.6)
        except Exception as e:
            print(f"[Внимание] Не удалось распарсить JSON зданий: {e}")

    # 3. Маркировка позиции игрока
    ax.scatter([player_x], [player_y], c='red', s=150, marker='X', label='Моя позиция')
    
    plt.title("Автономно-кастомная карта Припяти")
    plt.legend()
    plt.show()

def process_ocr():
    print("[OCR] Поиск координат...")
    left, top, right, bottom = 10, 900, 300, 1050
    screen_zone = ImageGrab.grab(bbox=(left, top, right, bottom)).convert("L")
    text = pytesseract.image_to_string(screen_zone, config="--psm 6 -c tessedit_char_whitelist=0123456789")
    numbers = re.findall(r'\d+', text)

    if len(numbers) >= 2:
        try:
            val_x = float(numbers[0])
            val_y = float(numbers[1])
            print(f"[Отображение] Позиция: {val_x} / {val_y}")
            render_local_map(val_x, val_y)
        except ValueError:
            print("[Ошибка] Неверный формат чисел.")
    else:
        print("[Ошибка] Координаты не считались.")

print("[Запуск] Скрипт локальной карты активен. Нажмите 'M'...")
keyboard.add_hotkey('m', process_ocr)
keyboard.wait()
```