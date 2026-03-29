from aiogram import Router, types
from aiogram.filters import Command
from utils.api_client import upsert_user

router = Router()

@router.message(Command("start"))
async def cmd_start(message: types.Message):
    user = await upsert_user(message.from_user.id)
    
    await message.answer(
        f"👋 Welcome to **TeleExam AI**, {message.from_user.first_name}!\n\n"
        "Ready to test your knowledge with AI-powered exams?\n\n"
        "Use the commands below:",
        parse_mode="Markdown"
    )
    
    await message.answer(
        "📋 Available Commands:\n"
        "/exam - Start a full exam\n"
        "/practice - Practice specific topic\n"
        "/quiz - Quick quiz mode\n"
        "/history - View your results\n"
        "/help - Show help"
    )