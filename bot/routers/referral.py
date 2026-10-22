from aiogram import F, Router
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton
from bot.services.api_client import api_client
from bot.config import settings
from bot.utils.text import esc

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
    
    # Build the unlock rules from the admin-configured invitation rules
    app_settings = await api_client.get_app_settings()
    rules = app_settings.get("invitation_rules") or {}
    free_years = rules.get("free_years", 1)
    invites_per_year = rules.get("invites_per_year", 1)
    years_per_invite = rules.get("years_per_invite", 1)
    max_invite_years = rules.get("max_invite_years", 1)
    free_courses_pct = round(float(rules.get("free_courses_ratio", 0.25)) * 100)
    courses_per_invite = rules.get("courses_per_invite", 1)
    ai_bonus = rules.get("ai_bonus_per_invite", 0)

    if years_per_invite > 1:
        year_rule = f"Each invite unlocks <b>{years_per_invite}</b> more exam years"
    elif invites_per_year > 1:
        year_rule = f"Every <b>{invites_per_year}</b> invites unlock 1 more exam year"
    else:
        year_rule = "Each invite unlocks <b>1</b> more exam year"

    rule_lines = [
        f"  • <b>Free:</b> oldest {free_years} exam year(s) and {free_courses_pct}% of courses",
        f"  • {year_rule} (up to <b>{max_invite_years}</b> extra year(s) by invites)",
        f"  • Each invite unlocks <b>{courses_per_invite}</b> more course(s)",
    ]
    if ai_bonus > 0:
        rule_lines.append(f"  • +{ai_bonus} free AI explanations per day for each invite")
    rule_lines.append(
        f"  • 💎 <b>Newest exam year &amp; full access:</b> PRO only — {settings.PRO_PRICE_BIRR} Birr"
    )

    journey = (
        "<b>🤝 Referral Program</b>\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "Invite your peers to study together and unlock more content.\n\n"
        f"👤 <b>Total Referrals:</b> <code>{invite_count}</code>\n"
        "<b>How invites unlock content:</b>\n"
        + "\n".join(rule_lines) + "\n\n"
        "<i>A friend counts only after they start the bot and choose their department.</i>\n"
        "━━━━━━━━━━━━━━━━━━\n\n"
        f"<b>📊 Your Invite Link:</b>\n"
        f"<code>{bot_link}</code>\n\n"
        "<i>Tap to copy, then share with your study groups!</i>"
    )
    
    # Show invited users if any
    if invited_users and len(invited_users) > 0:
        journey += "\n<b>👥 People You Invited:</b>\n"
        for i, user in enumerate(invited_users[:10], 1):  # Show top 10
            name = user.get("full_name") or user.get("first_name") or "User"
            joined = user.get("created_at", "")[:10] if user.get("created_at") else "N/A"
            # Older backends don't send department_chosen; treat that as counted
            if user.get("department_chosen", True):
                status = "✅ counted"
            else:
                status = "⏳ not counted yet: hasn't chosen a department"
            journey += f"  {i}. <b>{esc(name)}</b> - {esc(joined)} · {status}\n"
        if len(invited_users) > 10:
            journey += f"  ... and {len(invited_users) - 10} more\n"
        pending = sum(1 for u in invited_users if not u.get("department_chosen", True))
        if pending:
            journey += (
                f"\n⚠️ <b>{pending}</b> friend{'s' if pending > 1 else ''} joined but "
                f"{'have' if pending > 1 else 'has'} not chosen a department yet. "
                "Ask them to open the bot and pick their department so the invite counts.\n"
            )
    
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

