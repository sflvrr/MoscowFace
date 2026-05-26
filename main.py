import asyncio
import json
import os
import re
from datetime import datetime

from aiogram import Bot, Dispatcher, F, types
from aiogram.enums import ParseMode
from aiogram.filters import Command, CommandStart, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import KeyboardButton, ReplyKeyboardMarkup
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
ROUTES_FILE = "data/routes.json"

ADMIN_IDS = {
    int(x.strip())
    for x in os.getenv("ADMIN_IDS", "").split(",")
    if x.strip().isdigit()
}

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())

user_lang: dict[int, str] = {}
user_route: dict[int, int] = {}
user_progress: dict[str, int] = {}

with open("data/texts.json", "r", encoding="utf-8") as f:
    TEXTS: dict = json.load(f)

GO_BUTTONS = {TEXTS[lang]["go"] for lang in TEXTS}
AT_PLACE_BUTTONS = {TEXTS[lang]["at_place"] for lang in TEXTS}

SKIP_VOICE = "⏭ Пропустить голосовое"
SKIP_LOCATION = "⏭ Пропустить локацию"


# ─── Клавиатуры ───────────────────────────────────────────────────────────────

def make_kb(rows: list[list[str]]) -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text=btn) for btn in row] for row in rows],
        resize_keyboard=True
    )


def lang_kb() -> ReplyKeyboardMarkup:
    return make_kb([["🇷🇺 Русский", "🇬🇧 English"]])


def admin_kb() -> ReplyKeyboardMarkup:
    return make_kb([
        ["🗺 Создать маршрут"],
        ["✏️ Редактировать маршруты", "📋 Все маршруты"],
        ["🗑 Удалить маршрут"],
        ["❌ Закрыть админку"],
    ])


def cancel_kb() -> ReplyKeyboardMarkup:
    return make_kb([["❌ Отмена"]])


def voice_kb() -> ReplyKeyboardMarkup:
    """Клавиатура при запросе голосового — можно пропустить."""
    return make_kb([[SKIP_VOICE], ["❌ Отмена"]])


def location_kb() -> ReplyKeyboardMarkup:
    """Клавиатура при запросе локации — можно пропустить."""
    return make_kb([[SKIP_LOCATION], ["❌ Отмена"]])


def create_next_kb() -> ReplyKeyboardMarkup:
    return make_kb([
        ["➕ Добавить точку"],
        ["✅ Завершить маршрут"],
        ["❌ Отмена"],
    ])


def point_action_kb() -> ReplyKeyboardMarkup:
    return make_kb([
        ["📝 Изменить текст"],
        ["🎙 Заменить голосовое"],
        ["📍 Изменить локацию"],
        ["🗑 Удалить точку"],
        ["⬅️ К списку точек"],
        ["⬅️ К списку маршрутов"],
        ["⬅️ Админка"],
    ])


def user_go_kb(lang: str) -> ReplyKeyboardMarkup:
    return make_kb([[TEXTS[lang]["go"]], ["🧭 Выбрать другой маршрут"]])


def user_at_place_kb(lang: str) -> ReplyKeyboardMarkup:
    return make_kb([[TEXTS[lang]["at_place"]], ["🧭 Выбрать другой маршрут"]])


def route_list_kb() -> ReplyKeyboardMarkup | types.ReplyKeyboardRemove:
    routes = load_routes().get("routes", [])
    if not routes:
        return types.ReplyKeyboardRemove()
    rows = [[f"Маршрут: {route['title']}"] for route in routes]
    return make_kb(rows)


def admin_routes_kb() -> ReplyKeyboardMarkup:
    routes = load_routes().get("routes", [])
    rows = [
        [f"Редактировать маршрут {i + 1}: {route['title']}"]
        for i, route in enumerate(routes)
    ]
    rows.append(["⬅️ Админка"])
    return make_kb(rows)


def admin_delete_routes_kb() -> ReplyKeyboardMarkup:
    routes = load_routes().get("routes", [])
    rows = [
        [f"Удалить маршрут {i + 1}: {route['title']}"]
        for i, route in enumerate(routes)
    ]
    rows.append(["⬅️ Админка"])
    return make_kb(rows)


def route_points_kb(route: dict) -> ReplyKeyboardMarkup:
    rows = [[f"Точка {i + 1}"] for i in range(len(route.get("points", [])))]
    rows.append(["➕ Добавить точку"])
    rows.append(["⬅️ К списку маршрутов"])
    rows.append(["⬅️ Админка"])
    return make_kb(rows)


# ─── Работа с данными ─────────────────────────────────────────────────────────

def ensure_routes_file() -> None:
    os.makedirs("data", exist_ok=True)
    if not os.path.exists(ROUTES_FILE):
        save_routes({"routes": []})


def load_routes() -> dict:
    ensure_routes_file()
    with open(ROUTES_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)
    if "routes" not in data:
        data["routes"] = []
    return data


def save_routes(data: dict) -> None:
    os.makedirs("data", exist_ok=True)
    with open(ROUTES_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def get_route_by_id(route_id: int) -> dict | None:
    for route in load_routes().get("routes", []):
        if route["id"] == route_id:
            return route
    return None


def get_route_by_title(title: str) -> dict | None:
    for route in load_routes().get("routes", []):
        if route["title"] == title:
            return route
    return None


def save_route(updated_route: dict) -> bool:
    data = load_routes()
    for i, route in enumerate(data.get("routes", [])):
        if route["id"] == updated_route["id"]:
            data["routes"][i] = updated_route
            save_routes(data)
            return True
    return False


def delete_route_by_id(route_id: int) -> bool:
    data = load_routes()
    before = len(data["routes"])
    data["routes"] = [r for r in data["routes"] if r["id"] != route_id]
    if len(data["routes"]) < before:
        save_routes(data)
        return True
    return False


def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS


def google_maps_url(lat: float, lon: float) -> str:
    return f"https://www.google.com/maps?q={lat},{lon}"


def parse_location(text: str | None) -> dict | None:
    if not text:
        return None
    patterns = [
        r"@(-?\d+\.\d+),\s*(-?\d+\.\d+)",
        r"q=(-?\d+\.\d+),\s*(-?\d+\.\d+)",
        r"query=(-?\d+\.\d+),\s*(-?\d+\.\d+)",
        r"(-?\d+\.\d+),\s*(-?\d+\.\d+)",
    ]
    for pattern in patterns:
        match = re.search(pattern, text.strip())
        if match:
            return {
                "lat": float(match.group(1)),
                "lon": float(match.group(2)),
                "maps_url": text.strip(),
            }
    return None


def point_text(point: dict, index: int | None = None, total: int | None = None) -> str:
    if index is not None and total is not None:
        title = f"Точка {index + 1} из {total}"
    elif index is not None:
        title = f"Точка {index + 1}"
    else:
        title = "Точка"

    result = f"<b>{title}</b>\n\n{point['text']}"

    if point.get("lat") is not None and point.get("lon") is not None:
        maps_url = point.get("maps_url") or google_maps_url(point["lat"], point["lon"])
        result += f"\n\n📍 <code>{point['lat']}, {point['lon']}</code>\n🗺 {maps_url}"

    return result


def progress_key(user_id: int, route_id: int) -> str:
    return f"{user_id}:{route_id}"


def is_go_button(text: str | None) -> bool:
    if not text:
        return False
    return text.strip() in GO_BUTTONS


def is_at_place_button(text: str | None) -> bool:
    if not text:
        return False
    return text.strip() in AT_PLACE_BUTTONS


# ─── FSM состояния ────────────────────────────────────────────────────────────

class RouteState(StatesGroup):
    create_title = State()
    create_text = State()
    create_voice = State()
    create_location = State()
    create_next = State()
    edit_choose_route = State()
    edit_choose_point = State()
    edit_point_action = State()
    edit_text = State()
    edit_voice = State()
    edit_location = State()
    edit_add_text = State()
    edit_add_voice = State()
    edit_add_location = State()
    delete_choose_route = State()


# ─── Вспомогательные функции ──────────────────────────────────────────────────

async def show_user_routes(message: types.Message, lang: str) -> None:
    routes = load_routes().get("routes", [])
    if not routes:
        text = "Маршруты пока не созданы." if lang == "ru" else "No routes available yet."
        await message.answer(text)
        return
    text = "Выбери маршрут:" if lang == "ru" else "Choose a route:"
    await message.answer(text, reply_markup=route_list_kb())


async def show_admin_routes(message: types.Message) -> None:
    routes = load_routes().get("routes", [])
    if not routes:
        await message.answer("Маршруты ещё не созданы.", reply_markup=admin_kb())
        return
    await message.answer("Выбери маршрут для редактирования:", reply_markup=admin_routes_kb())


async def show_edit_menu(message: types.Message, route: dict) -> None:
    await message.answer(
        f"✏️ <b>Редактирование маршрута</b>\n\n"
        f"Название: <b>{route['title']}</b>\n"
        f"ID: <code>{route['id']}</code>\n"
        f"Точек: <b>{len(route.get('points', []))}</b>\n\n"
        f"Выбери точку или добавь новую.",
        parse_mode=ParseMode.HTML,
        reply_markup=route_points_kb(route),
    )


async def ask_voice(message: types.Message, state: FSMContext, next_state: State) -> None:
    """Переходит в состояние запроса голосового с кнопкой пропуска."""
    await state.set_state(next_state)
    await message.answer(
        "Отправь голосовое сообщение или пропусти.",
        reply_markup=voice_kb(),
    )


async def ask_location(message: types.Message, state: FSMContext, next_state: State) -> None:
    """Переходит в состояние запроса локации с кнопкой пропуска."""
    await state.set_state(next_state)
    await message.answer(
        "Отправь локацию или пропусти.\n\n"
        "Пример: <code>55.751244, 37.618423</code>\n"
        "или ссылку Google Maps:\n"
        "https://www.google.com/maps?q=55.751244,37.618423",
        parse_mode=ParseMode.HTML,
        reply_markup=location_kb(),
    )


async def finalize_point(message: types.Message, state: FSMContext, target: str) -> None:
    """
    Финализирует точку и сохраняет её.
    target = "current_point" — при создании маршрута,
    target = "new_point"     — при добавлении точки в существующий маршрут.
    """
    data = await state.get_data()
    point = data[target]

    if target == "current_point":
        route = data["route"]
        route["points"].append(point)
        await state.update_data(route=route, current_point={})
        await state.set_state(RouteState.create_next)
        await message.answer(
            f"✅ Точка добавлена. Всего точек: <b>{len(route['points'])}</b>",
            parse_mode=ParseMode.HTML,
            reply_markup=create_next_kb(),
        )
    else:
        route = get_route_by_id(data["edit_route_id"])
        if route is None:
            await state.clear()
            await message.answer("Маршрут не найден.", reply_markup=admin_kb())
            return
        route["points"].append(point)
        save_route(route)
        await state.update_data(new_point={})
        await state.set_state(RouteState.edit_choose_point)
        await message.answer(
            f"✅ Новая точка добавлена. Всего точек: <b>{len(route['points'])}</b>",
            parse_mode=ParseMode.HTML,
            reply_markup=route_points_kb(route),
        )


# ─── Общие команды ────────────────────────────────────────────────────────────

@dp.message(CommandStart())
async def cmd_start(message: types.Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer("Выбери язык / Choose your language:", reply_markup=lang_kb())


@dp.message(Command("admin"))
async def cmd_admin(message: types.Message) -> None:
    if not is_admin(message.from_user.id):
        await message.answer("⛔ Нет доступа.")
        return
    await message.answer("Админ-панель:", reply_markup=admin_kb())


@dp.message(F.text == "❌ Отмена")
async def cancel_action(message: types.Message, state: FSMContext) -> None:
    await state.clear()
    if is_admin(message.from_user.id):
        await message.answer("Действие отменено.", reply_markup=admin_kb())
    else:
        lang = user_lang.get(message.from_user.id, "ru")
        await message.answer(
            "Отменено." if lang == "ru" else "Cancelled.",
            reply_markup=types.ReplyKeyboardRemove(),
        )


@dp.message(F.text == "❌ Закрыть админку")
async def close_admin(message: types.Message, state: FSMContext) -> None:
    if not is_admin(message.from_user.id):
        return
    await state.clear()
    await message.answer("Админ-панель закрыта.", reply_markup=types.ReplyKeyboardRemove())


# ─── Выбор языка и маршрута ───────────────────────────────────────────────────

@dp.message(F.text.in_(["🇷🇺 Русский", "🇬🇧 English"]))
async def set_language(message: types.Message, state: FSMContext) -> None:
    if is_admin(message.from_user.id):
        current_state = await state.get_state()
        if current_state is not None:
            return

    lang = "ru" if "Рус" in message.text else "en"
    user_lang[message.from_user.id] = lang
    user_route.pop(message.from_user.id, None)

    await message.answer(TEXTS[lang]["start"])
    await show_user_routes(message, lang)


@dp.message(F.text == "🧭 Выбрать другой маршрут")
async def choose_another_route(message: types.Message) -> None:
    lang = user_lang.get(message.from_user.id, "ru")
    user_route.pop(message.from_user.id, None)
    await show_user_routes(message, lang)


@dp.message(F.text.startswith("Маршрут: "))
async def select_user_route(message: types.Message) -> None:
    lang = user_lang.get(message.from_user.id, "ru")
    title = message.text[len("Маршрут: "):]
    route = get_route_by_title(title)

    if route is None:
        await message.answer("Маршрут не найден.")
        return

    user_route[message.from_user.id] = route["id"]
    user_progress[progress_key(message.from_user.id, route["id"])] = 0

    await message.answer(
        f"Выбран маршрут: <b>{route['title']}</b>\n\n"
        f"Точек: <b>{len(route.get('points', []))}</b>",
        parse_mode=ParseMode.HTML,
        reply_markup=user_go_kb(lang),
    )


# ─── Прохождение маршрута ─────────────────────────────────────────────────────

async def send_point(message: types.Message, route: dict, point: dict, index: int, lang: str) -> None:
    """Отправляет одну точку маршрута пользователю."""
    points = route.get("points", [])

    await message.answer(
        f"<b>{route['title']}</b>\n\n" + point_text(point, index, len(points)),
        parse_mode=ParseMode.HTML,
        reply_markup=user_at_place_kb(lang),
    )

    # Локация — только если есть координаты
    if point.get("lat") is not None and point.get("lon") is not None:
        await message.answer_location(latitude=point["lat"], longitude=point["lon"])

    # Голосовое — только если есть
    if point.get("voice_file_id"):
        await message.answer_voice(point["voice_file_id"])


@dp.message(F.func(lambda m: is_go_button(m.text)))
async def send_place_info(message: types.Message) -> None:
    user_id = message.from_user.id
    lang = user_lang.get(user_id, "ru")
    route_id = user_route.get(user_id)

    if route_id is None:
        await show_user_routes(message, lang)
        return

    route = get_route_by_id(route_id)
    if route is None:
        user_route.pop(user_id, None)
        await message.answer("Маршрут не найден.")
        await show_user_routes(message, lang)
        return

    points = route.get("points", [])
    if not points:
        await message.answer("В этом маршруте пока нет точек.")
        return

    key = progress_key(user_id, route_id)
    index = user_progress.get(key, 0)

    if index >= len(points):
        await message.answer(TEXTS[lang]["thanks"], reply_markup=types.ReplyKeyboardRemove())
        return

    await send_point(message, route, points[index], index, lang)


@dp.message(F.func(lambda m: is_at_place_button(m.text)))
async def at_place(message: types.Message) -> None:
    user_id = message.from_user.id
    lang = user_lang.get(user_id, "ru")
    route_id = user_route.get(user_id)

    if route_id is None:
        await show_user_routes(message, lang)
        return

    route = get_route_by_id(route_id)
    if route is None:
        user_route.pop(user_id, None)
        await message.answer("Маршрут не найден.")
        await show_user_routes(message, lang)
        return

    points = route.get("points", [])
    key = progress_key(user_id, route_id)
    index = user_progress.get(key, 0)

    if index >= len(points):
        await message.answer(TEXTS[lang]["thanks"], reply_markup=types.ReplyKeyboardRemove())
        return

    next_index = index + 1
    user_progress[key] = next_index

    if next_index >= len(points):
        await message.answer(TEXTS[lang]["thanks"], reply_markup=types.ReplyKeyboardRemove())
        return

    await send_point(message, route, points[next_index], next_index, lang)


# ─── Admin: просмотр маршрутов ────────────────────────────────────────────────

@dp.message(F.text == "📋 Все маршруты")
async def show_all_routes(message: types.Message) -> None:
    if not is_admin(message.from_user.id):
        return

    routes = load_routes().get("routes", [])
    if not routes:
        await message.answer("Маршруты ещё не созданы.", reply_markup=admin_kb())
        return

    lines = ["<b>📋 Все маршруты</b>", ""]
    for i, route in enumerate(routes, 1):
        lines.append(
            f"<b>{i}. {route['title']}</b>\n"
            f"ID: <code>{route['id']}</code>\n"
            f"Точек: <b>{len(route.get('points', []))}</b>"
        )

    await message.answer("\n\n".join(lines), parse_mode=ParseMode.HTML, reply_markup=admin_kb())


# ─── Admin: создание маршрута ─────────────────────────────────────────────────

@dp.message(F.text == "🗺 Создать маршрут")
async def create_route_start(message: types.Message, state: FSMContext) -> None:
    if not is_admin(message.from_user.id):
        return
    await state.set_state(RouteState.create_title)
    await message.answer("Введи название маршрута.", reply_markup=cancel_kb())


@dp.message(StateFilter(RouteState.create_title))
async def create_route_title(message: types.Message, state: FSMContext) -> None:
    if not is_admin(message.from_user.id):
        return
    if not message.text or message.text == "❌ Отмена":
        return

    route = {
        "id": int(datetime.now().timestamp()),
        "title": message.text.strip(),
        "created_at": datetime.now().isoformat(),
        "points": [],
    }
    await state.update_data(route=route, current_point={})
    await state.set_state(RouteState.create_text)
    await message.answer("Введи текст описания первой точки.", reply_markup=cancel_kb())


@dp.message(StateFilter(RouteState.create_text))
async def create_point_text(message: types.Message, state: FSMContext) -> None:
    if not is_admin(message.from_user.id):
        return
    if not message.text or message.text == "❌ Отмена":
        return

    data = await state.get_data()
    point = data.get("current_point", {})
    point["text"] = message.text
    await state.update_data(current_point=point)
    await ask_voice(message, state, RouteState.create_voice)


@dp.message(StateFilter(RouteState.create_voice), F.voice)
async def create_point_voice(message: types.Message, state: FSMContext) -> None:
    if not is_admin(message.from_user.id):
        return

    data = await state.get_data()
    point = data.get("current_point", {})
    point["voice_file_id"] = message.voice.file_id
    point["voice_duration"] = message.voice.duration
    await state.update_data(current_point=point)
    await ask_location(message, state, RouteState.create_location)


@dp.message(StateFilter(RouteState.create_voice), F.text == SKIP_VOICE)
async def create_point_voice_skip(message: types.Message, state: FSMContext) -> None:
    if not is_admin(message.from_user.id):
        return
    # Голосовое пропущено — переходим к локации
    await ask_location(message, state, RouteState.create_location)


@dp.message(StateFilter(RouteState.create_voice))
async def create_point_voice_wrong(message: types.Message) -> None:
    if is_admin(message.from_user.id):
        await message.answer("Отправь голосовое сообщение или нажми «Пропустить».", reply_markup=voice_kb())


@dp.message(StateFilter(RouteState.create_location), F.text == SKIP_LOCATION)
async def create_point_location_skip(message: types.Message, state: FSMContext) -> None:
    if not is_admin(message.from_user.id):
        return
    # Локация пропущена — сохраняем точку без координат
    await finalize_point(message, state, "current_point")


@dp.message(StateFilter(RouteState.create_location))
async def create_point_location(message: types.Message, state: FSMContext) -> None:
    if not is_admin(message.from_user.id):
        return

    location = parse_location(message.text)
    if location is None:
        await message.answer(
            "Не удалось распознать координаты.\n\n"
            "Отправь, например: <code>55.751244, 37.618423</code>\n"
            "или нажми «Пропустить».",
            parse_mode=ParseMode.HTML,
            reply_markup=location_kb(),
        )
        return

    data = await state.get_data()
    point = data.get("current_point", {})
    point.update(location)
    await state.update_data(current_point=point)
    await finalize_point(message, state, "current_point")


@dp.message(StateFilter(RouteState.create_next))
async def create_next_action(message: types.Message, state: FSMContext) -> None:
    if not is_admin(message.from_user.id):
        return

    if message.text == "➕ Добавить точку":
        await state.update_data(current_point={})
        await state.set_state(RouteState.create_text)
        await message.answer("Введи текст описания следующей точки.", reply_markup=cancel_kb())
        return

    if message.text == "✅ Завершить маршрут":
        data = await state.get_data()
        route = data["route"]

        if not route["points"]:
            await message.answer("Нельзя сохранить пустой маршрут. Добавь хотя бы одну точку.")
            return

        routes_data = load_routes()
        routes_data["routes"].append(route)
        save_routes(routes_data)
        await state.clear()

        await message.answer(
            f"✅ Маршрут сохранён!\n\n"
            f"Название: <b>{route['title']}</b>\n"
            f"ID: <code>{route['id']}</code>\n"
            f"Точек: <b>{len(route['points'])}</b>",
            parse_mode=ParseMode.HTML,
            reply_markup=admin_kb(),
        )
        return

    await message.answer("Выбери действие кнопкой.", reply_markup=create_next_kb())


# ─── Admin: редактирование маршрутов ─────────────────────────────────────────

@dp.message(F.text == "✏️ Редактировать маршруты")
async def edit_routes_start(message: types.Message, state: FSMContext) -> None:
    if not is_admin(message.from_user.id):
        return
    await state.set_state(RouteState.edit_choose_route)
    await show_admin_routes(message)


@dp.message(StateFilter(RouteState.edit_choose_route))
async def edit_choose_route(message: types.Message, state: FSMContext) -> None:
    if not is_admin(message.from_user.id):
        return

    if message.text == "⬅️ Админка":
        await state.clear()
        await message.answer("Админ-панель:", reply_markup=admin_kb())
        return

    match = re.fullmatch(r"Редактировать маршрут (\d+): .+", message.text or "")
    if not match:
        await message.answer("Выбери маршрут кнопкой.", reply_markup=admin_routes_kb())
        return

    index = int(match.group(1)) - 1
    routes = load_routes().get("routes", [])

    if index < 0 or index >= len(routes):
        await message.answer("Маршрут не найден.", reply_markup=admin_routes_kb())
        return

    route = routes[index]
    await state.update_data(edit_route_id=route["id"])
    await state.set_state(RouteState.edit_choose_point)
    await show_edit_menu(message, route)


@dp.message(StateFilter(RouteState.edit_choose_point))
async def edit_choose_point(message: types.Message, state: FSMContext) -> None:
    if not is_admin(message.from_user.id):
        return

    data = await state.get_data()
    route = get_route_by_id(data.get("edit_route_id"))

    if route is None:
        await state.clear()
        await message.answer("Маршрут не найден.", reply_markup=admin_kb())
        return

    if message.text == "⬅️ Админка":
        await state.clear()
        await message.answer("Админ-панель:", reply_markup=admin_kb())
        return

    if message.text == "⬅️ К списку маршрутов":
        await state.set_state(RouteState.edit_choose_route)
        await show_admin_routes(message)
        return

    if message.text == "➕ Добавить точку":
        await state.update_data(new_point={})
        await state.set_state(RouteState.edit_add_text)
        await message.answer("Введи текст новой точки.", reply_markup=cancel_kb())
        return

    match = re.fullmatch(r"Точка (\d+)", message.text or "")
    if not match:
        await message.answer("Выбери точку кнопкой.", reply_markup=route_points_kb(route))
        return

    index = int(match.group(1)) - 1
    points = route.get("points", [])

    if index < 0 or index >= len(points):
        await message.answer("Точка не найдена.", reply_markup=route_points_kb(route))
        return

    await state.update_data(edit_index=index)
    await state.set_state(RouteState.edit_point_action)
    await message.answer(
        point_text(points[index], index, len(points)),
        parse_mode=ParseMode.HTML,
        reply_markup=point_action_kb(),
    )


@dp.message(StateFilter(RouteState.edit_point_action))
async def edit_point_action(message: types.Message, state: FSMContext) -> None:
    if not is_admin(message.from_user.id):
        return

    data = await state.get_data()
    route = get_route_by_id(data.get("edit_route_id"))
    index = data.get("edit_index")

    if route is None or index is None:
        await state.clear()
        await message.answer("Маршрут не найден.", reply_markup=admin_kb())
        return

    points = route.get("points", [])
    if index < 0 or index >= len(points):
        await state.clear()
        await message.answer("Точка не найдена.", reply_markup=admin_kb())
        return

    if message.text == "📝 Изменить текст":
        await state.set_state(RouteState.edit_text)
        await message.answer("Отправь новый текст.", reply_markup=cancel_kb())
        return

    if message.text == "🎙 Заменить голосовое":
        await state.set_state(RouteState.edit_voice)
        await message.answer("Отправь новое голосовое сообщение или пропусти (удалит текущее).", reply_markup=voice_kb())
        return

    if message.text == "📍 Изменить локацию":
        await state.set_state(RouteState.edit_location)
        await message.answer(
            "Отправь новую локацию или пропусти (удалит текущую).\n\n"
            "Пример: <code>55.751244, 37.618423</code>",
            parse_mode=ParseMode.HTML,
            reply_markup=location_kb(),
        )
        return

    if message.text == "🗑 Удалить точку":
        deleted = points.pop(index)
        route["points"] = points
        save_route(route)
        await state.set_state(RouteState.edit_choose_point)
        await message.answer(
            f"🗑 Точка удалена:\n\n{deleted['text']}",
            reply_markup=route_points_kb(route),
        )
        return

    if message.text == "⬅️ К списку точек":
        await state.set_state(RouteState.edit_choose_point)
        await show_edit_menu(message, route)
        return

    if message.text == "⬅️ К списку маршрутов":
        await state.set_state(RouteState.edit_choose_route)
        await show_admin_routes(message)
        return

    if message.text == "⬅️ Админка":
        await state.clear()
        await message.answer("Админ-панель:", reply_markup=admin_kb())
        return

    await message.answer("Выбери действие кнопкой.", reply_markup=point_action_kb())


@dp.message(StateFilter(RouteState.edit_text))
async def edit_text_save(message: types.Message, state: FSMContext) -> None:
    if not is_admin(message.from_user.id):
        return
    if not message.text:
        await message.answer("Нужно отправить текст.")
        return

    data = await state.get_data()
    route = get_route_by_id(data["edit_route_id"])
    index = data["edit_index"]

    route["points"][index]["text"] = message.text
    save_route(route)

    await state.set_state(RouteState.edit_point_action)
    await message.answer("✅ Текст обновлён.", reply_markup=point_action_kb())


@dp.message(StateFilter(RouteState.edit_voice), F.voice)
async def edit_voice_save(message: types.Message, state: FSMContext) -> None:
    if not is_admin(message.from_user.id):
        return

    data = await state.get_data()
    route = get_route_by_id(data["edit_route_id"])
    index = data["edit_index"]

    route["points"][index]["voice_file_id"] = message.voice.file_id
    route["points"][index]["voice_duration"] = message.voice.duration
    save_route(route)

    await state.set_state(RouteState.edit_point_action)
    await message.answer("✅ Голосовое обновлено.", reply_markup=point_action_kb())


@dp.message(StateFilter(RouteState.edit_voice), F.text == SKIP_VOICE)
async def edit_voice_skip(message: types.Message, state: FSMContext) -> None:
    if not is_admin(message.from_user.id):
        return

    data = await state.get_data()
    route = get_route_by_id(data["edit_route_id"])
    index = data["edit_index"]

    route["points"][index].pop("voice_file_id", None)
    route["points"][index].pop("voice_duration", None)
    save_route(route)

    await state.set_state(RouteState.edit_point_action)
    await message.answer("✅ Голосовое удалено.", reply_markup=point_action_kb())


@dp.message(StateFilter(RouteState.edit_voice))
async def edit_voice_wrong(message: types.Message) -> None:
    if is_admin(message.from_user.id):
        await message.answer("Отправь голосовое сообщение или нажми «Пропустить».", reply_markup=voice_kb())


@dp.message(StateFilter(RouteState.edit_location), F.text == SKIP_LOCATION)
async def edit_location_skip(message: types.Message, state: FSMContext) -> None:
    if not is_admin(message.from_user.id):
        return

    data = await state.get_data()
    route = get_route_by_id(data["edit_route_id"])
    index = data["edit_index"]

    route["points"][index].pop("lat", None)
    route["points"][index].pop("lon", None)
    route["points"][index].pop("maps_url", None)
    save_route(route)

    await state.set_state(RouteState.edit_point_action)
    await message.answer("✅ Локация удалена.", reply_markup=point_action_kb())


@dp.message(StateFilter(RouteState.edit_location))
async def edit_location_save(message: types.Message, state: FSMContext) -> None:
    if not is_admin(message.from_user.id):
        return

    location = parse_location(message.text)
    if location is None:
        await message.answer(
            "Не удалось распознать координаты.\n\n"
            "Пример: <code>55.751244, 37.618423</code>\n"
            "или нажми «Пропустить».",
            parse_mode=ParseMode.HTML,
            reply_markup=location_kb(),
        )
        return

    data = await state.get_data()
    route = get_route_by_id(data["edit_route_id"])
    index = data["edit_index"]

    route["points"][index].update(location)
    save_route(route)

    await state.set_state(RouteState.edit_point_action)
    await message.answer("✅ Локация обновлена.", reply_markup=point_action_kb())


# ─── Admin: добавление точки в существующий маршрут ──────────────────────────

@dp.message(StateFilter(RouteState.edit_add_text))
async def edit_add_text(message: types.Message, state: FSMContext) -> None:
    if not is_admin(message.from_user.id):
        return
    if not message.text:
        await message.answer("Нужно отправить текст.")
        return

    data = await state.get_data()
    point = data.get("new_point", {})
    point["text"] = message.text
    await state.update_data(new_point=point)
    await ask_voice(message, state, RouteState.edit_add_voice)


@dp.message(StateFilter(RouteState.edit_add_voice), F.voice)
async def edit_add_voice(message: types.Message, state: FSMContext) -> None:
    if not is_admin(message.from_user.id):
        return

    data = await state.get_data()
    point = data.get("new_point", {})
    point["voice_file_id"] = message.voice.file_id
    point["voice_duration"] = message.voice.duration
    await state.update_data(new_point=point)
    await ask_location(message, state, RouteState.edit_add_location)


@dp.message(StateFilter(RouteState.edit_add_voice), F.text == SKIP_VOICE)
async def edit_add_voice_skip(message: types.Message, state: FSMContext) -> None:
    if not is_admin(message.from_user.id):
        return
    await ask_location(message, state, RouteState.edit_add_location)


@dp.message(StateFilter(RouteState.edit_add_voice))
async def edit_add_voice_wrong(message: types.Message) -> None:
    if is_admin(message.from_user.id):
        await message.answer("Отправь голосовое сообщение или нажми «Пропустить».", reply_markup=voice_kb())


@dp.message(StateFilter(RouteState.edit_add_location), F.text == SKIP_LOCATION)
async def edit_add_location_skip(message: types.Message, state: FSMContext) -> None:
    if not is_admin(message.from_user.id):
        return
    await finalize_point(message, state, "new_point")


@dp.message(StateFilter(RouteState.edit_add_location))
async def edit_add_location(message: types.Message, state: FSMContext) -> None:
    if not is_admin(message.from_user.id):
        return

    location = parse_location(message.text)
    if location is None:
        await message.answer(
            "Не удалось распознать координаты.\n\n"
            "Пример: <code>55.751244, 37.618423</code>\n"
            "или нажми «Пропустить».",
            parse_mode=ParseMode.HTML,
            reply_markup=location_kb(),
        )
        return

    data = await state.get_data()
    point = data.get("new_point", {})
    point.update(location)
    await state.update_data(new_point=point)
    await finalize_point(message, state, "new_point")


# ─── Admin: удаление маршрута ─────────────────────────────────────────────────

@dp.message(F.text == "🗑 Удалить маршрут")
async def delete_route_start(message: types.Message, state: FSMContext) -> None:
    if not is_admin(message.from_user.id):
        return

    routes = load_routes().get("routes", [])
    if not routes:
        await message.answer("Нет маршрутов для удаления.", reply_markup=admin_kb())
        return

    await state.set_state(RouteState.delete_choose_route)
    await message.answer("Выбери маршрут для удаления:", reply_markup=admin_delete_routes_kb())


@dp.message(StateFilter(RouteState.delete_choose_route))
async def delete_choose_route(message: types.Message, state: FSMContext) -> None:
    if not is_admin(message.from_user.id):
        return

    if message.text == "⬅️ Админка":
        await state.clear()
        await message.answer("Админ-панель:", reply_markup=admin_kb())
        return

    match = re.fullmatch(r"Удалить маршрут (\d+): .+", message.text or "")
    if not match:
        await message.answer("Выбери маршрут кнопкой.", reply_markup=admin_delete_routes_kb())
        return

    index = int(match.group(1)) - 1
    routes = load_routes().get("routes", [])

    if index < 0 or index >= len(routes):
        await message.answer("Маршрут не найден.", reply_markup=admin_delete_routes_kb())
        return

    route = routes[index]
    title = route["title"]
    delete_route_by_id(route["id"])
    await state.clear()

    await message.answer(
        f"🗑 Маршрут <b>{title}</b> удалён.",
        parse_mode=ParseMode.HTML,
        reply_markup=admin_kb(),
    )


# ─── Запуск ───────────────────────────────────────────────────────────────────

async def main() -> None:
    ensure_routes_file()
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())