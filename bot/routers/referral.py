from aiogram import F, Router
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton
from bot.services.api_client import api_client
from bot.config import settings

router = Router()

@router.message(F.text == "🤝 Invite Friends")
async def referral_dashboard(message: Message):
    if not message.from_user:
        return

    # Fetch user data and invited users from backend
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
    
    # Fetch invited users
    invited_users = await api_client.get(
        path="/api/users/invited",
        telegram_id=message.from_user.id
    )
    
    bot_link = f"https://t.me/TeleExamAI_bot?start=ref_{invite_code}"
    
    # Build referral journey text
    journey = (
        "<b>🤝 Referral Program</b>\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "Invite your peers to study together and unlock advanced content.\n\n"
        f"👤 <b>Total Referrals:</b> <code>{invite_count}</code>\n"
        "<b>Content Unlock Sequence:</b>\n"
        "  • <b>1 Referral:</b> Unlocks 2nd Year exams\n"
        "  • <b>2 Referrals:</b> Unlocks 3rd Year exams\n"
        "  • <b>3 Referrals:</b> Unlocks 4th Year exams\n"
        "  • <b>4 Referrals:</b> Full Access to all content\n"
        "━━━━━━━━━━━━━━━━━━\n\n"
        f"<b>📊 Your Invite Link:</b>\n"
        f"<code>{bot_link}</code>\n\n"
        "<i>Tap to copy, then share with your study groups!</i>"
    )
    
    # Show invited users if any
    if invited_users and len(invited_users) > 0:
        journey += "\n<b>👥 People You Invited:</b>\n"
        for i, user in enumerate(invited_users[:10], 1):  # Show top 10
            name = user.get("first_name", "User")
            joined = user.get("created_at", "")[:10] if user.get("created_at") else "N/A"
            journey += f"  {i}. <b>{name}</b> - {joined}\n"
        if len(invited_users) > 10:
            journey += f"  ... and {len(invited_users) - 10} more\n"
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📤 Share Link", url=f"https://t.me/share/url?url={bot_link}&text=Study%20better%20with%20TeleExam%20AI!%20Unlocking%20years%20of%20past%20exams%20now.")]
    ])

    await message.answer(journey, parse_mode="HTML", reply_markup=keyboard)


@router.message(F.text)
async def fallback_text_handler(message: Message) -> None:
    """Fallback handler for unhandled text messages. Guides the user to use menu buttons."""
    if not message.from_user:
        return

    from bot.keyboards.reply import main_menu_keyboard

    await message.answer(
        "⚠️ <b>Unrecognized Input.</b>\n\n"
        "Please select an option from the menu buttons below:",
        parse_mode="HTML",
        reply_markup=main_menu_keyboard(),
    )

