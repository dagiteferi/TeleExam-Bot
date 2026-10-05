import logging
from io import BytesIO

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
import aiohttp

from bot.services.api_client import api_client
from bot.states.session_states import Payment
from bot.keyboards.reply import main_menu_keyboard

logger = logging.getLogger(__name__)

router = Router()


@router.message(F.text == "⭐️ Upgrade to PRO")
async def upgrade_to_pro_menu(message: Message, state: FSMContext) -> None:
    if not message.from_user:
        return

    # Check active bank accounts from backend
    banks = await api_client.get(
        path="/api/payments/banks",
        telegram_id=message.from_user.id,
    )

    if not banks:
        # Fallback list if database has no active bank records yet
        banks = [
            {
                "bank_name": "Commercial Bank of Ethiopia (CBE)",
                "account_name": "TeleExam AI",
                "account_number": "1000123456789",
            },
            {
                "bank_name": "Telebirr",
                "account_name": "TeleExam AI",
                "account_number": "0911223344",
            },
        ]

    banks_text = "⭐️ <b>Upgrade to TeleExam AI PRO</b>\n"
    banks_text += "━━━━━━━━━━━━━━━━━━\n"
    banks_text += "Unlock unlimited AI Tutor explanations, all past exams, and premium practice sessions!\n\n"
    banks_text += "<b>💳 Payment Instructions:</b>\n"
    banks_text += "Transfer payment to any of the bank accounts below, then send a screenshot of the receipt.\n\n"

    for bank in banks:
        banks_text += f"🏦 <b>{bank.get('bank_name')}</b>\n"
        banks_text += f"👤 <b>Account Name:</b> {bank.get('account_name')}\n"
        banks_text += f"🔢 <b>Account Number:</b> <code>{bank.get('account_number')}</code>\n\n"

    banks_text += "━━━━━━━━━━━━━━━━━━\n"
    banks_text += "Click the button below when you are ready to upload your screenshot."

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📸 Upload Receipt Screenshot", callback_data="upload_payment_screenshot")],
    ])

    await message.answer(banks_text, parse_mode="HTML", reply_markup=keyboard)


@router.callback_query(F.data == "upload_payment_screenshot")
async def start_upload_screenshot(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    await state.set_state(Payment.uploading_screenshot)
    await callback.message.answer(
        "📸 <b>Upload Screenshot</b>\n\n"
        "Please send the photo/screenshot of your payment transfer now.\n\n"
        "<i>To cancel, send /cancel or pick a menu option.</i>",
        parse_mode="HTML",
    )


@router.message(Payment.uploading_screenshot, F.photo)
async def process_screenshot_upload(message: Message, state: FSMContext) -> None:
    if not message.from_user or not message.photo:
        return

    # Get the highest resolution photo
    photo = message.photo[-1]
    bot = message.bot

    await message.answer("⏳ Uploading your payment receipt, please wait...")

    try:
        # Download photo into memory
        file_io = BytesIO()
        await bot.download(photo, destination=file_io)
        file_bytes = file_io.getvalue()

        # Prepare form data
        form_data = aiohttp.FormData()
        form_data.add_field(
            name="file",
            value=file_bytes,
            filename=f"receipt_{message.from_user.id}.jpg",
            content_type="image/jpeg",
        )

        res = await api_client.post_multipart(
            path="/api/payments/submit",
            telegram_id=message.from_user.id,
            form_data=form_data,
        )

        if res:
            await state.set_state(None)
            await message.answer(
                "✅ <b>Payment Receipt Received!</b>\n\n"
                "Thank you! Your submission is now under admin review.\n"
                "Once approved, your account will automatically be upgraded to <b>PRO</b>!",
                parse_mode="HTML",
                reply_markup=main_menu_keyboard(),
            )
        else:
            await message.answer(
                "❌ <b>Upload Failed</b>\n\n"
                "There was an issue submitting your payment receipt. Please try again.",
                parse_mode="HTML",
                reply_markup=main_menu_keyboard(),
            )
            await state.set_state(None)
    except Exception as e:
        logger.exception("Error uploading payment screenshot:")
        await message.answer(
            "❌ An error occurred while processing your receipt. Please try again later.",
            reply_markup=main_menu_keyboard(),
        )
        await state.set_state(None)


@router.message(Payment.uploading_screenshot, F.text == "/cancel")
async def cancel_upload(message: Message, state: FSMContext) -> None:
    await state.set_state(None)
    await message.answer("Cancelled payment upload.", reply_markup=main_menu_keyboard())


@router.message(F.photo)
async def handle_photo_outside_state(message: Message, state: FSMContext) -> None:
    """Catch photos sent outside the FSM payment state and guide the user."""
    current_state = await state.get_state()
    if current_state == Payment.uploading_screenshot:
        # Already handled by the handler above — shouldn't reach here
        return

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📸 Start Payment Upload", callback_data="upload_payment_screenshot")],
    ])
    await message.answer(
        "📸 <b>Were you trying to submit a payment receipt?</b>\n\n"
        "Please click the button below to start the upload process properly.",
        parse_mode="HTML",
        reply_markup=keyboard,
    )

