from aiogram import F, Router
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton
from bot.services.api_client import api_client
from bot.config import settings

router = Router()

@router.message(F.text == "🤝 Invite Friends")
async def referral_dashboard(message: Message):
    if not message.from_user:
        return

    # Fetch latest user stats from backend
    # We use upsert without payload to just get current data if needed, 
    # or better, we could have a dedicated stats endpoint.
    # Since upsert returns invite_count and invite_code, let's use it.
    user_data = await api_client.post(
        path="/api/users/upsert",
        telegram_id=message.from_user.id,
        payload={"telegram_id": message.from_user.id} 
    )

    if not user_data:
        await message.answer("Failed to load referral data. Please try again later.")
        return

    invite_count = user_data.get("invite_count", 0)
    invite_code = user_data.get("invite_code")
    bot_username = settings.BOT_TOKEN.split(":")[0] # Fallback, better to get from bot instance
    # In aiogram 3, we can get bot username from bot object, but for now we'll use a placeholder
    # or better, from config if available.
    
    bot_link = f"https://t.me/TeleExamAI_bot?start=ref_{invite_code}"
    
    # 4-Invite Journey Description
    journey = (
        "<b>Referral Program</b>\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "Invite your peers to study together and unlock advanced content.\n\n"
        f"Total Referrals: <b>{invite_count}</b>\n\n"
        "<b>Content Unlock Sequence:</b>\n"
        "• <b>1 Referral:</b> Unlocks 2nd Year of exams\n"
        "• <b>2 Referrals:</b> Unlocks 3rd Year of exams\n"
        "• <b>3 Referrals:</b> Unlocks 4th Year of exams\n"
        "• <b>4 Referrals:</b> Full Access to all exams and practice materials\n\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "<b>Your Unique Invite Link:</b>\n"
        f"<code>{bot_link}</code>\n\n"
        "<i>Tap the link to copy it, then share it with your study groups.</i>"
    )

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Share Link", url=f"https://t.me/share/url?url={bot_link}&text=Study%20better%20with%20TeleExam%20AI!%20Unlocking%20years%20of%20past%20exams%20now.")]
    ])

    await message.answer(journey, parse_mode="HTML", reply_markup=keyboard)
