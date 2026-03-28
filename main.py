import asyncio
import logging
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.utils.keyboard import InlineKeyboardBuilder
from dotenv import load_dotenv
import httpx
import os

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
BACKEND_URL = "https://teleexam-ai.hf.space"

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# ====================== START COMMAND ======================
@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    builder = InlineKeyboardBuilder()
    builder.button(text="📝 Start Exam", callback_data="mode:exam")
    builder.button(text="📚 Practice Mode", callback_data="mode:practice")
    builder.button(text="⚡ Quick Quiz", callback_data="mode:quiz")
    builder.adjust(1)

    await message.answer(
        "👋 Welcome to **TeleExam AI**!\n\n"
        "Ready to test your knowledge with AI-powered exams?\n\n"
        "Choose what you want to do:",
        reply_markup=builder.as_markup()
    )

# ====================== BUTTON CALLBACKS ======================
@dp.callback_query()
async def handle_mode_selection(callback: types.CallbackQuery):
    if not callback.data.startswith("mode:"):
        await callback.answer("Unknown action")
        return

    mode = callback.data.split(":")[1]   # exam, practice, or quiz

    await callback.message.edit_text(f"🔄 Starting **{mode.upper()}** mode...\nPlease wait while we prepare your session...")

    try:
        # Call your backend
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{BACKEND_URL}/api/exam/start",
                params={"mode": mode},
                headers={"X-Telegram-Secret": os.getenv("TELEGRAM_WEBHOOK_SECRET", "")},
                timeout=30.0
            )
            
            data = response.json()

        if data.get("success", True) and "session_id" in data:
            session_id = data["session_id"]
            question = data.get("next_question", {})

            await show_question(callback.message, question, session_id)
        else:
            await callback.message.answer("❌ Failed to start session. Please try again.")

    except Exception as e:
        logging.error(f"Error starting exam: {e}")
        await callback.message.answer("❌ Sorry, could not connect to the server. Please try again later.")

    await callback.answer()

# Function to display the question nicely
async def show_question(message: types.Message, question: dict, session_id: str):
    if not question:
        await message.answer("No question received.")
        return

    text = f"❓ **Question:**\n\n{question.get('text', 'No question text')}"

    builder = InlineKeyboardBuilder()
    options = question.get("options", [])
    for option in options:
        # Extract letter (A, B, C, D)
        letter = option[0] if option and len(option) > 1 else "?"
        builder.button(
            text=option, 
            callback_data=f"answer:{session_id}:{question.get('question_id')}:{letter}"
        )

    builder.button(text="❌ End Exam", callback_data=f"end:{session_id}")
    builder.adjust(1)

    if question.get("image_url"):
        await message.answer_photo(
            photo=question["image_url"],
            caption=text,
            reply_markup=builder.as_markup(),
            parse_mode="Markdown"
        )
    else:
        await message.answer(
            text, 
            reply_markup=builder.as_markup(),
            parse_mode="Markdown"
        )

async def main():
    logging.basicConfig(level=logging.INFO)
    print("🚀 TeleExam AI Bot is running...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())