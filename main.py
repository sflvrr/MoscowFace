import json
import os
from aiogram import Bot, Dispatcher, F, types
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton
from aiogram.filters import CommandStart
from aiogram.enums import ParseMode
from aiogram.types.input_file import FSInputFile
from dotenv import load_dotenv

load_dotenv()
bot = Bot(token=os.getenv("BOT_TOKEN"))
dp = Dispatcher()


user_lang = {}
user_progress = {}


with open("data/texts.json", "r", encoding="utf-8") as f:
    TEXTS = json.load(f)

with open("data/places.json", "r", encoding="utf-8") as f:
    PLACES = json.load(f)


@dp.message(CommandStart())
async def start(message: types.Message):
    kb = ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="🇷🇺 Русский"), KeyboardButton(text="🇬🇧 English")]
        ],
        resize_keyboard=True
    )
    await message.answer("Выбери язык / Choose your language:", reply_markup=kb)


@dp.message(F.text.in_(["🇷🇺 Русский", "🇬🇧 English"]))
async def set_language(message: types.Message):
    lang = "ru" if "Рус" in message.text else "en"
    user_lang[message.from_user.id] = lang
    user_progress[message.from_user.id] = 0  # начинаем с первого места

    kb = ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text=TEXTS[lang]["go"])]],
        resize_keyboard=True
    )
    await message.answer(TEXTS[lang]["start"], reply_markup=kb)


@dp.message(lambda msg: any(msg.text == TEXTS[lang]["go"] for lang in TEXTS))
async def send_place_info(message: types.Message):
    lang = user_lang.get(message.from_user.id, "ru")
    index = user_progress.get(message.from_user.id, 0)

    if index >= len(PLACES):
        await message.answer(TEXTS[lang]["thanks"], reply_markup=types.ReplyKeyboardRemove())
        return

    place = PLACES[index]
    text = (
        f"<b>{place['title'][lang]}</b>\n\n"
        f"{place['description'][lang]}\n\n"
        f"📍 {place['route'][lang]}"
    )

    kb = ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text=TEXTS[lang]["at_place"])]],
        resize_keyboard=True
    )

    await message.answer(text, parse_mode=ParseMode.HTML, reply_markup=kb)
    await message.answer_location(latitude=place["lat"], longitude=place["lon"])


@dp.message(lambda msg: any(msg.text == TEXTS[lang]["at_place"] for lang in TEXTS))
async def at_place(message: types.Message):
    lang = user_lang.get(message.from_user.id, "ru")
    index = user_progress.get(message.from_user.id, 0)

    if index >= len(PLACES):
        await message.answer(TEXTS[lang]["thanks"], reply_markup=types.ReplyKeyboardRemove())
        return

    place = PLACES[index]
    video_path = f"data/circles/{place['circle_video'][lang]}"

    if os.path.exists(video_path):
        video = FSInputFile(video_path)
        await bot.send_video_note(chat_id=message.chat.id, video_note=video)

    await message.answer(place["circle_text"][lang])

    user_progress[message.from_user.id] = index + 1

    if index + 1 < len(PLACES):
        kb = ReplyKeyboardMarkup(
            keyboard=[[KeyboardButton(text=TEXTS[lang]["go"])]],
            resize_keyboard=True
        )
        await message.answer("🚶‍♀️ " + TEXTS[lang]["go"], reply_markup=kb)
    else:
        await message.answer(TEXTS[lang]["thanks"], reply_markup=types.ReplyKeyboardRemove())


if __name__ == "__main__":
    import asyncio
    asyncio.run(dp.start_polling(bot))