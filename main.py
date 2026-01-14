import logging
import re
import asyncio
import os
import hashlib
from datetime import datetime
from aiogram import Bot, Dispatcher, Router, F
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import Message, CallbackQuery, ChatShared
from aiogram.enums import ChatType, ChatMemberStatus

from pyrogram import Client
from pyrogram.errors import (
    PhoneCodeInvalid, PhoneCodeExpired, SessionPasswordNeeded,
    PasswordHashInvalid, PhoneNumberInvalid, FloodWait
)

from config import BOT_TOKEN, ADMINS, SESSIONS_DIR, REFERRAL_REWARD, MIN_WITHDRAWAL
import database as db
import keyboards as kb

# Logging sozlash
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Sessions papkasini yaratish
os.makedirs(SESSIONS_DIR, exist_ok=True)

# Bot va Dispatcher
bot = Bot(token=BOT_TOKEN, parse_mode="HTML")
storage = MemoryStorage()
dp = Dispatcher(storage=storage)
router = Router()
dp.include_router(router)

# Aktiv Pyrogram clientlar
active_clients = {}

# ============ FSM States ============

class AddChannelState(StatesGroup):
    waiting_for_channel = State()

class AddRequestChannelState(StatesGroup):
    waiting_for_link = State()
    waiting_for_channel_selection = State()

class DeleteChannelState(StatesGroup):
    waiting_for_selection = State()

class SearchUserState(StatesGroup):
    waiting_for_query = State()

class PhoneDetectState(StatesGroup):
    waiting_for_user_id = State()

class BroadcastState(StatesGroup):
    waiting_for_message = State()
    confirm = State()

class TelegramLoginState(StatesGroup):
    waiting_for_api_id = State()
    waiting_for_api_hash = State()
    waiting_for_phone = State()
    waiting_for_code = State()
    waiting_for_2fa = State()
    service_type = State()  # 'clock' yoki 'online'

class AddBotState(StatesGroup):
    waiting_for_username = State()

class WithdrawState(StatesGroup):
    waiting_for_card = State()

# ============ Yordamchi funksiyalar ============

def is_admin(user_id):
    """Admin ekanligini tekshirish"""
    return user_id in ADMINS

def estimate_registration_date(user_id):
    """Telegram ID asosida taxminiy ro'yxatdan o'tish sanasini hisoblash"""
    known_points = [
        (1, datetime(2013, 8, 1)),
        (100000000, datetime(2014, 10, 1)),
        (200000000, datetime(2015, 8, 1)),
        (300000000, datetime(2016, 5, 1)),
        (400000000, datetime(2017, 1, 1)),
        (500000000, datetime(2017, 8, 1)),
        (600000000, datetime(2018, 3, 1)),
        (700000000, datetime(2018, 9, 1)),
        (800000000, datetime(2019, 3, 1)),
        (900000000, datetime(2019, 8, 1)),
        (1000000000, datetime(2020, 2, 1)),
        (1100000000, datetime(2020, 6, 1)),
        (1200000000, datetime(2020, 10, 1)),
        (1300000000, datetime(2021, 2, 1)),
        (1400000000, datetime(2021, 5, 1)),
        (1500000000, datetime(2021, 8, 1)),
        (1600000000, datetime(2021, 11, 1)),
        (1700000000, datetime(2022, 2, 1)),
        (1800000000, datetime(2022, 5, 1)),
        (1900000000, datetime(2022, 8, 1)),
        (2000000000, datetime(2022, 10, 1)),
        (5000000000, datetime(2023, 3, 1)),
        (6000000000, datetime(2023, 9, 1)),
        (7000000000, datetime(2024, 3, 1)),
        (8000000000, datetime(2024, 10, 1)),
    ]
    
    if user_id <= known_points[0][0]:
        return known_points[0][1]
    if user_id >= known_points[-1][0]:
        return known_points[-1][1]
    
    for i in range(len(known_points) - 1):
        if known_points[i][0] <= user_id < known_points[i + 1][0]:
            id1, date1 = known_points[i]
            id2, date2 = known_points[i + 1]
            ratio = (user_id - id1) / (id2 - id1)
            delta = date2 - date1
            estimated = date1 + (delta * ratio)
            return estimated
    
    return datetime.now()

async def check_bot_started(user_id, bot_username):
    """Foydalanuvchi botni ishga tushirganini tekshirish"""
    # Bu funksiya foydalanuvchi botni ishga tushirganini tekshiradi
    # Hozircha bazadagi yozuvni tekshiramiz
    return db.has_bot_started(user_id, bot_username)

async def check_user_subscription(user_id):
    """Foydalanuvchi barcha kanallarga obuna bo'lganini tekshirish"""
    channels = db.get_active_channels()
    
    if not channels:
        return True
    
    for channel in channels:
        channel_id = channel['channel_id']
        is_request_channel = channel.get('is_request_channel', 0)
        is_bot = channel.get('is_bot', 0)
        
        try:
            if is_bot:
                # Bot - faqat ro'yxatda ko'rsatiladi, tekshirilmaydi
                continue
            elif is_request_channel:
                if db.has_join_request(user_id, channel_id):
                    continue
                else:
                    return False
            else:
                member = await bot.get_chat_member(chat_id=channel_id, user_id=user_id)
                if member.status not in [ChatMemberStatus.MEMBER, ChatMemberStatus.ADMINISTRATOR, 
                                         ChatMemberStatus.CREATOR, ChatMemberStatus.RESTRICTED]:
                    return False
        except Exception as e:
            logger.error(f"Kanal tekshirishda xato ({channel_id}): {e}")
            continue
    
    return True

async def require_subscription(message: Message):
    """Obuna talab qilish"""
    channels = db.get_active_channels()
    if not channels:
        return True
    
    # Faqat obuna bo'lmagan kanallarni topish
    not_subscribed_channels = []
    # Botlar ro'yxati (faqat ko'rsatish uchun)
    bot_channels = []
    user_id = message.from_user.id
    
    for channel in channels:
        channel_id = channel['channel_id']
        is_request_channel = channel.get('is_request_channel', 0)
        is_bot = channel.get('is_bot', 0)
        
        try:
            if is_bot:
                # Bot - faqat ro'yxatda ko'rsatish uchun, majburiy emas
                bot_channels.append(channel)
            elif is_request_channel:
                # So'rovli kanal - join request borligini tekshirish
                if not db.has_join_request(user_id, channel_id):
                    not_subscribed_channels.append(channel)
            else:
                # Oddiy kanal - a'zolikni tekshirish
                member = await bot.get_chat_member(chat_id=channel_id, user_id=user_id)
                if member.status not in [ChatMemberStatus.MEMBER, ChatMemberStatus.ADMINISTRATOR, 
                                         ChatMemberStatus.CREATOR, ChatMemberStatus.RESTRICTED]:
                    not_subscribed_channels.append(channel)
        except Exception as e:
            logger.error(f"Kanal tekshirishda xato ({channel_id}): {e}")
            not_subscribed_channels.append(channel)
    
    if not_subscribed_channels:
        # Majburiy kanallar + botlar (ko'rsatish uchun)
        all_channels = not_subscribed_channels + bot_channels
        text = "📢 <b>Botdan foydalanish uchun quyidagi kanallarga obuna bo'ling:</b>"
        await message.answer(text, reply_markup=kb.check_subscription_keyboard(all_channels))
        return False
    
    return True

def format_user_info(user_data, history=None):
    """Foydalanuvchi ma'lumotlarini formatlash"""
    reg_date = estimate_registration_date(user_data['user_id'])
    
    text = f"👤 <b>Foydalanuvchi ma'lumotlari</b>\n\n"
    text += f"🆔 <b>ID:</b> <code>{user_data['user_id']}</code>\n"
    text += f"👤 <b>Ism:</b> {user_data['first_name'] or 'Kiritilmagan'}\n"
    text += f"👥 <b>Familiya:</b> {user_data['last_name'] or 'Kiritilmagan'}\n"
    text += f"📧 <b>Username:</b> @{user_data['username']}\n" if user_data['username'] else f"📧 <b>Username:</b> Kiritilmagan\n"
    text += f"📱 <b>Telefon:</b> {user_data['phone_number'] or 'Kiritilmagan'}\n"
    text += f"🌐 <b>Til:</b> {user_data['language_code'] or 'Noma`lum'}\n"
    text += f"⭐ <b>Premium:</b> {'Ha' if user_data['is_premium'] else 'Yo`q'}\n"
    text += f"📅 <b>Telegram ro'yxatdan o'tish:</b> ~{reg_date.strftime('%Y-%m-%d')}\n"
    text += f"📅 <b>Botda ro'yxatdan o'tish:</b> {user_data['created_at']}\n"
    text += f"🔄 <b>Oxirgi yangilanish:</b> {user_data['updated_at']}\n"
    
    if history:
        text += f"\n📜 <b>O'zgarishlar:</b> {len(history)} ta\n"
    
    return text

# ============ Start va asosiy handlerlar ============

# Kerakli referal soni
REQUIRED_REFERRALS = 5

@router.message(Command("start"), StateFilter("*"))
async def cmd_start(message: Message, state: FSMContext):
    """Start buyrug'i"""
    await state.clear()
    
    db.add_or_update_user(message.from_user)
    
    # Referal tekshirish (start=ref_123456)
    args = message.text.split()
    if len(args) > 1 and args[1].startswith("ref_"):
        try:
            referrer_id = int(args[1].replace("ref_", ""))
            if referrer_id != message.from_user.id and not db.has_referrer(message.from_user.id):
                db.add_referral(referrer_id, message.from_user.id)
                # Taklif qilgan odamga pul qo'shish
                db.add_balance(referrer_id, REFERRAL_REWARD)
                # Taklif qilgan odamga xabar yuborish
                try:
                    ref_count = db.get_referral_count(referrer_id)
                    balance_info = db.get_user_balance(referrer_id)
                    await bot.send_message(
                        referrer_id, 
                        f"🎉 <b>Yangi referal!</b>\n\n"
                        f"👤 <b>{message.from_user.first_name}</b> sizning havolangiz orqali qo'shildi.\n\n"
                        f"💰 <b>+{REFERRAL_REWARD:,} so'm</b> balansingizga qo'shildi!\n"
                        f"💵 Joriy balans: <b>{balance_info['balance']:,}</b> so'm\n"
                        f"👥 Jami referallar: <b>{ref_count}</b> ta"
                    )
                except:
                    pass
        except:
            pass
    
    if not await require_subscription(message):
        return
    
    await message.answer(
        f"👋 Salom, <b>{message.from_user.first_name}</b>!\n\n"
        f"Botdan foydalanish uchun quyidagi tugmani bosing:",
        reply_markup=kb.main_menu_keyboard()
    )

@router.message(Command("admin"), StateFilter("*"))
async def cmd_admin(message: Message, state: FSMContext):
    """Admin panel"""
    await state.clear()
    
    if not is_admin(message.from_user.id):
        await message.answer("❌ Sizda admin huquqlari yo'q!")
        return
    
    await message.answer(
        "🔐 <b>Admin panel</b>\n\n"
        "Quyidagi tugmalardan birini tanlang:",
        reply_markup=kb.admin_panel_reply_keyboard()
    )

# ============ Xizmatlar menyusi handlerlari ============

async def check_referral_requirement(message: Message):
    """Referal talabini tekshirish"""
    user_id = message.from_user.id
    
    # Adminlar uchun tekshiruv shart emas
    if is_admin(user_id):
        return True
    
    ref_count = db.get_referral_count(user_id)
    
    if ref_count < REQUIRED_REFERRALS:
        bot_info = await bot.get_me()
        ref_link = f"https://t.me/{bot_info.username}?start=ref_{user_id}"
        
        await message.answer(
            f"🔒 <b>Xizmatlarga kirish uchun {REQUIRED_REFERRALS} ta do'stingizni taklif qiling!</b>\n\n"
            f"📊 Hozirgi referallaringiz: <b>{ref_count}/{REQUIRED_REFERRALS}</b>\n\n"
            f"📎 Sizning referal havolangiz:\n<code>{ref_link}</code>\n\n"
            f"Do'stlaringizga yuboring va ular /start bosganidan keyin sizga hisoblanadi!",
            reply_markup=kb.referral_keyboard(bot_info.username, user_id)
        )
        return False
    
    return True

@router.message(F.text == "🗂 Xizmatlar", StateFilter("*"))
async def show_services(message: Message, state: FSMContext):
    """Xizmatlar menyusini ko'rsatish"""
    await state.clear()
    
    if not await require_subscription(message):
        return
    
    # Referal tekshirish
    if not await check_referral_requirement(message):
        return
    
    await message.answer(
        "🔐 <b>Xizmatlar</b>\n\n"
        "Quyidagi xizmatlardan birini tanlang:",
        reply_markup=kb.services_keyboard()
    )

@router.message(F.text == "👥 Referal", StateFilter("*"))
async def show_referral(message: Message, state: FSMContext):
    """Referal bo'limini ko'rsatish"""
    await state.clear()
    
    if not await require_subscription(message):
        return
    
    user_id = message.from_user.id
    ref_count = db.get_referral_count(user_id)
    balance_info = db.get_user_balance(user_id)
    bot_info = await bot.get_me()
    ref_link = f"https://t.me/{bot_info.username}?start=ref_{user_id}"
    
    balance = balance_info['balance']
    total_earned = balance_info['total_earned']
    
    status = "✅ Xizmatlarga kirish ochiq!" if ref_count >= REQUIRED_REFERRALS else f"🔒 Xizmatlarga kirish uchun yana {REQUIRED_REFERRALS - ref_count} ta referal kerak"
    
    await message.answer(
        f"👥 <b>Referal tizimi - Pul ishlang!</b>\n\n"
        f"💰 <b>Har bir taklif uchun:</b> {REFERRAL_REWARD:,} so'm\n"
        f"📤 <b>Minimal yechish:</b> {MIN_WITHDRAWAL:,} so'm\n\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"📊 <b>Sizning statistikangiz:</b>\n"
        f"👥 Jami referallar: <b>{ref_count}</b> ta\n"
        f"💵 Joriy balans: <b>{balance:,}</b> so'm\n"
        f"💰 Jami ishlangan: <b>{total_earned:,}</b> so'm\n"
        f"━━━━━━━━━━━━━━━━━━\n\n"
        f"{status}\n\n"
        f"📎 <b>Sizning referal havolangiz:</b>\n<code>{ref_link}</code>\n\n"
        f"💡 Do'stlaringizga yuboring - ular /start bosishi bilan sizga {REFERRAL_REWARD:,} so'm tushadi!",
        reply_markup=kb.referral_keyboard(bot_info.username, user_id)
    )

@router.message(F.text == "🆘 Qo'llab-quvvatlash", StateFilter("*"))
async def show_support(message: Message, state: FSMContext):
    """Qo'llab-quvvatlash bo'limi"""
    await state.clear()
    
    if not await require_subscription(message):
        return
    
    await message.answer(
        "🆘 <b>Qo'llab-quvvatlash</b>\n\n"
        "Savollaringiz yoki muammolaringiz bo'lsa, bizga murojaat qiling:\n\n"
        "📢 Kanal: @daromatx\n"
        "👤 Admin: @daromatx_admin",
        reply_markup=kb.main_menu_keyboard()
    )

@router.message(F.text == "⬅️ Orqaga", StateFilter("*"))
async def back_to_main(message: Message, state: FSMContext):
    """Bosh menyuga qaytish"""
    await state.clear()
    await message.answer(
        "🏠 <b>Bosh menyu</b>",
        reply_markup=kb.main_menu_keyboard()
    )

@router.message(F.text == "📱 Telefon raqamini aniqlash", StateFilter("*"))
async def phone_detect_service(message: Message, state: FSMContext):
    """Telefon raqamini aniqlash xizmati"""
    await state.clear()
    
    if not await require_subscription(message):
        return
    
    if not await check_referral_requirement(message):
        return
    
    await state.set_state(PhoneDetectState.waiting_for_user_id)
    await message.answer(
        "📱 <b>Telefon raqamini aniqlash</b>\n\n"
        "Foydalanuvchining Telegram ID raqamini yoki @username ni yuboring:\n\n"
        "📌 <i>Masalan: 123456789 yoki @username</i>\n\n"
        "❌ Bekor qilish uchun /cancel buyrug'ini yuboring",
        reply_markup=kb.services_keyboard()
    )

@router.message(PhoneDetectState.waiting_for_user_id)
async def process_phone_detect(message: Message, state: FSMContext):
    """Telefon raqamini qidirish"""
    query = message.text.strip()
    
    if query == "⬅️ Ortga":
        await state.clear()
        await message.answer(
            "🗂 <b>Xizmatlar bo'limi</b>\n\n"
            "Quyidagi xizmatlardan birini tanlang:",
            reply_markup=kb.services_keyboard()
        )
        return
    
    if query.startswith("/"):
        await state.clear()
        return
    
    user_info = None
    
    # Username yoki ID bilan qidirish
    if query.startswith("@"):
        username = query[1:]
        user_info = db.get_user_by_username(username)
    elif query.isdigit():
        user_id = int(query)
        user_info = db.get_user(user_id)
    else:
        # Username @ siz ham qabul qilinadi
        user_info = db.get_user_by_username(query)
    
    if user_info:
        phone = user_info.get('phone_number') or user_info['phone_number'] if 'phone_number' in user_info.keys() else None
        
        first_name = user_info['first_name'] or "Noma'lum"
        
        if phone:
            result_text = (
                f"📱 <b>Telefon raqami topildi!</b>\n\n"
                f"👤 Ism: {first_name}\n"
                f"🆔 ID: <code>{user_info['user_id']}</code>\n"
                f"📞 Telefon: <code>{phone}</code>\n"
            )
            if user_info.get('username'):
                result_text += f"📧 Username: @{user_info['username']}\n"
        else:
            result_text = (
                f"📱 <b>Foydalanuvchi topildi</b>\n\n"
                f"👤 Ism: {first_name}\n"
                f"🆔 ID: <code>{user_info['user_id']}</code>\n"
            )
            if user_info.get('username'):
                result_text += f"📧 Username: @{user_info['username']}\n"
            result_text += "\n⚠️ <i>Telefon raqami bazada mavjud emas</i>"
    else:
        result_text = (
            "❌ <b>Foydalanuvchi topilmadi!</b>\n\n"
            "Bu foydalanuvchi botdan foydalanmagan yoki bazada mavjud emas."
        )
    
    await message.answer(result_text, reply_markup=kb.services_keyboard())
    await state.clear()

# ============ Telegram Login (Pyrogram) ============

async def start_telegram_login(message: Message, state: FSMContext, service_type: str):
    """Telegram loginni boshlash"""
    user_id = message.from_user.id
    
    # Mavjud sessiyani tekshirish
    existing_session = db.get_user_session(user_id)
    
    if existing_session and existing_session.get('session_string'):
        # Sessiya mavjud - to'g'ridan-to'g'ri xizmatni yoqish
        if service_type == 'clock':
            db.update_session_settings(user_id, clock_enabled=True)
            await message.answer(
                "✅ <b>Profilga soat qo'yish yoqildi!</b>\n\n"
                "🕐 Har daqiqada profilingizga hozirgi vaqt qo'yiladi.\n\n"
                "❌ O'chirish uchun \"🕐 Soatni o'chirish\" tugmasini bosing.",
                reply_markup=kb.clock_control_keyboard()
            )
        else:  # online
            db.update_session_settings(user_id, online_enabled=True)
            await message.answer(
                "✅ <b>24/7 Online yoqildi!</b>\n\n"
                "🟢 Sizning akkauntingiz doimo online ko'rinadi.\n\n"
                "❌ O'chirish uchun \"🟢 Online ni o'chirish\" tugmasini bosing.",
                reply_markup=kb.online_control_keyboard()
            )
        return
    
    # Yangi login kerak - avval API_ID so'rash
    await state.update_data(service_type=service_type)
    await state.set_state(TelegramLoginState.waiting_for_api_id)
    
    await message.answer(
        "🔑 <b>Telegram API sozlamalari</b>\n\n"
        "Telegram akkauntingizga ulanish uchun API ma'lumotlari kerak.\n\n"
        "📋 <b>API_ID va API_HASH olish:</b>\n"
        "1️⃣ https://my.telegram.org saytiga kiring\n"
        "2️⃣ Telefon raqamingiz bilan login qiling\n"
        "3️⃣ \"API development tools\" bo'limiga o'ting\n"
        "4️⃣ App yarating (istalgan nom bering)\n"
        "5️⃣ API_ID va API_HASH ni oling\n\n"
        "🔢 <b>API_ID ni yuboring:</b>\n"
        "<i>(Faqat raqamlar, masalan: 12345678)</i>\n\n"
        "❌ Bekor qilish: /cancel",
        reply_markup=kb.cancel_keyboard()
    )

@router.message(TelegramLoginState.waiting_for_api_id)
async def process_api_id(message: Message, state: FSMContext):
    """API_ID ni qabul qilish"""
    if message.text == "❌ Bekor qilish" or message.text == "/cancel":
        await state.clear()
        await message.answer("❌ Bekor qilindi", reply_markup=kb.services_keyboard())
        return
    
    api_id = message.text.strip()
    
    if not api_id.isdigit():
        await message.answer(
            "❌ <b>Noto'g'ri API_ID!</b>\n\n"
            "API_ID faqat raqamlardan iborat bo'lishi kerak.\n"
            "Masalan: <code>12345678</code>"
        )
        return
    
    await state.update_data(api_id=api_id)
    await state.set_state(TelegramLoginState.waiting_for_api_hash)
    
    await message.answer(
        "🔐 <b>API_HASH ni yuboring:</b>\n\n"
        "<i>(32 ta belgi, masalan: 0123456789abcdef0123456789abcdef)</i>\n\n"
        "❌ Bekor qilish: /cancel"
    )

@router.message(TelegramLoginState.waiting_for_api_hash)
async def process_api_hash(message: Message, state: FSMContext):
    """API_HASH ni qabul qilish"""
    if message.text == "❌ Bekor qilish" or message.text == "/cancel":
        await state.clear()
        await message.answer("❌ Bekor qilindi", reply_markup=kb.services_keyboard())
        return
    
    api_hash = message.text.strip()
    
    if len(api_hash) != 32:
        await message.answer(
            "❌ <b>Noto'g'ri API_HASH!</b>\n\n"
            "API_HASH 32 ta belgidan iborat bo'lishi kerak.\n"
            "Masalan: <code>0123456789abcdef0123456789abcdef</code>"
        )
        return
    
    await state.update_data(api_hash=api_hash)
    await state.set_state(TelegramLoginState.waiting_for_phone)
    
    await message.answer(
        "📱 <b>Telefon raqamingizni yuboring:</b>\n\n"
        "Xalqaro formatda: <code>+998901234567</code>\n\n"
        "⚠️ Raqam Telegram akkauntingizga bog'langan bo'lishi kerak\n\n"
        "❌ Bekor qilish: /cancel"
    )

@router.message(TelegramLoginState.waiting_for_phone)
async def process_phone_number(message: Message, state: FSMContext):
    """Telefon raqamini qabul qilish"""
    if message.text == "❌ Bekor qilish" or message.text == "/cancel":
        await state.clear()
        await message.answer("❌ Bekor qilindi", reply_markup=kb.services_keyboard())
        return
    
    phone = message.text.strip()
    
    # Telefon raqamini tekshirish
    if not phone.startswith("+"):
        phone = "+" + phone
    
    # Faqat raqamlarni qoldirish (+ dan keyin)
    phone_digits = re.sub(r'[^\d+]', '', phone)
    
    if len(phone_digits) < 10:
        await message.answer(
            "❌ Noto'g'ri telefon raqami formati!\n\n"
            "To'g'ri format: <code>+998901234567</code>"
        )
        return
    
    user_id = message.from_user.id
    data = await state.get_data()
    
    # Foydalanuvchining API ma'lumotlarini olish
    user_api_id = int(data.get('api_id'))
    user_api_hash = data.get('api_hash')
    
    # Pyrogram client yaratish
    try:
        client = Client(
            name=f"{SESSIONS_DIR}/user_{user_id}",
            api_id=user_api_id,
            api_hash=user_api_hash,
            in_memory=True
        )
        
        await client.connect()
        
        # Kod yuborish
        sent_code = await client.send_code(phone_digits)
        
        await state.update_data(
            phone=phone_digits,
            phone_code_hash=sent_code.phone_code_hash
        )
        
        # client ni saqlash
        active_clients[user_id] = client
        
        await state.set_state(TelegramLoginState.waiting_for_code)
        
        await message.answer(
            f"📨 <b>Kod yuborildi!</b>\n\n"
            f"Telegram sizga <b>{phone_digits}</b> raqamiga kod yubordi.\n\n"
            f"🔢 Kodni yuboring:\n"
            f"<i>(5 xonali kod)</i>\n\n"
            f"❌ Bekor qilish: /cancel"
        )
        
    except PhoneNumberInvalid:
        await message.answer(
            "❌ <b>Noto'g'ri telefon raqami!</b>\n\n"
            "Iltimos, to'g'ri raqam yuboring."
        )
    except FloodWait as e:
        await message.answer(
            f"⏳ <b>Juda ko'p urinish!</b>\n\n"
            f"Iltimos, {e.value} soniya kutib turing."
        )
    except Exception as e:
        logger.error(f"Phone error: {e}")
        await message.answer(
            f"❌ <b>Xatolik yuz berdi:</b>\n{str(e)}\n\n"
            f"API_ID yoki API_HASH noto'g'ri bo'lishi mumkin."
        )

@router.message(TelegramLoginState.waiting_for_code)
async def process_code(message: Message, state: FSMContext):
    """Tasdiqlash kodini qabul qilish"""
    if message.text == "❌ Bekor qilish" or message.text == "/cancel":
        user_id = message.from_user.id
        if user_id in active_clients:
            await active_clients[user_id].disconnect()
            del active_clients[user_id]
        await state.clear()
        await message.answer("❌ Bekor qilindi", reply_markup=kb.services_keyboard())
        return
    
    code = message.text.strip().replace(" ", "").replace("-", "")
    
    if not code.isdigit():
        await message.answer("❌ Kod faqat raqamlardan iborat bo'lishi kerak!")
        return
    
    data = await state.get_data()
    user_id = message.from_user.id
    client = active_clients.get(user_id)
    
    if not client:
        await message.answer("❌ Sessiya tugadi. Qaytadan boshlang.")
        await state.clear()
        return
    
    try:
        await client.sign_in(
            phone_number=data['phone'],
            phone_code_hash=data['phone_code_hash'],
            phone_code=code
        )
        
        # Muvaffaqiyatli login
        session_string = await client.export_session_string()
        db.save_user_session(user_id, data['api_id'], data['api_hash'], data['phone'], session_string)
        
        # Xizmatni yoqish
        service_type = data.get('service_type', 'clock')
        
        if service_type == 'clock':
            db.update_session_settings(user_id, clock_enabled=True)
            await message.answer(
                "✅ <b>Muvaffaqiyatli ulandi!</b>\n\n"
                "🕐 Profilga soat qo'yish yoqildi!\n"
                "Har daqiqada profilingizga hozirgi vaqt qo'yiladi.",
                reply_markup=kb.clock_control_keyboard()
            )
        else:
            db.update_session_settings(user_id, online_enabled=True)
            await message.answer(
                "✅ <b>Muvaffaqiyatli ulandi!</b>\n\n"
                "🟢 24/7 Online yoqildi!\n"
                "Sizning akkauntingiz doimo online ko'rinadi.",
                reply_markup=kb.online_control_keyboard()
            )
        
        await state.clear()
        
    except SessionPasswordNeeded:
        # 2FA kerak
        await state.set_state(TelegramLoginState.waiting_for_2fa)
        await message.answer(
            "🔐 <b>Ikki bosqichli autentifikatsiya</b>\n\n"
            "Sizning akkauntingizda 2FA yoqilgan.\n"
            "Iltimos, parolingizni yuboring:\n\n"
            "❌ Bekor qilish: /cancel"
        )
        
    except PhoneCodeInvalid:
        await message.answer(
            "❌ <b>Noto'g'ri kod!</b>\n\n"
            "Iltimos, to'g'ri kodni yuboring."
        )
    except PhoneCodeExpired:
        await message.answer(
            "❌ <b>Kod eskirgan!</b>\n\n"
            "Iltimos, /cancel bosib, qaytadan boshlang."
        )
    except Exception as e:
        logger.error(f"Code error: {e}")
        await message.answer(f"❌ <b>Xatolik:</b> {str(e)}")

@router.message(TelegramLoginState.waiting_for_2fa)
async def process_2fa(message: Message, state: FSMContext):
    """2FA parolni qabul qilish"""
    if message.text == "❌ Bekor qilish" or message.text == "/cancel":
        user_id = message.from_user.id
        if user_id in active_clients:
            await active_clients[user_id].disconnect()
            del active_clients[user_id]
        await state.clear()
        await message.answer("❌ Bekor qilindi", reply_markup=kb.services_keyboard())
        return
    
    password = message.text.strip()
    data = await state.get_data()
    user_id = message.from_user.id
    client = active_clients.get(user_id)
    
    if not client:
        await message.answer("❌ Sessiya tugadi. Qaytadan boshlang.")
        await state.clear()
        return
    
    try:
        await client.check_password(password)
        
        # Muvaffaqiyatli login
        session_string = await client.export_session_string()
        db.save_user_session(user_id, data['api_id'], data['api_hash'], data['phone'], session_string)
        
        # Xizmatni yoqish
        service_type = data.get('service_type', 'clock')
        
        if service_type == 'clock':
            db.update_session_settings(user_id, clock_enabled=True)
            await message.answer(
                "✅ <b>Muvaffaqiyatli ulandi!</b>\n\n"
                "🕐 Profilga soat qo'yish yoqildi!\n"
                "Har daqiqada profilingizga hozirgi vaqt qo'yiladi.",
                reply_markup=kb.clock_control_keyboard()
            )
        else:
            db.update_session_settings(user_id, online_enabled=True)
            await message.answer(
                "✅ <b>Muvaffaqiyatli ulandi!</b>\n\n"
                "🟢 24/7 Online yoqildi!\n"
                "Sizning akkauntingiz doimo online ko'rinadi.",
                reply_markup=kb.online_control_keyboard()
            )
        
        await state.clear()
        
    except PasswordHashInvalid:
        await message.answer(
            "❌ <b>Noto'g'ri parol!</b>\n\n"
            "Iltimos, to'g'ri parolni yuboring."
        )
    except Exception as e:
        logger.error(f"2FA error: {e}")
        await message.answer(f"❌ <b>Xatolik:</b> {str(e)}")

@router.message(F.text == "🕐 Profilga soat qo'yish", StateFilter("*"))
async def profile_clock_service(message: Message, state: FSMContext):
    """Profilga soat qo'yish xizmati"""
    await state.clear()
    
    if not await require_subscription(message):
        return
    
    if not await check_referral_requirement(message):
        return
    
    await start_telegram_login(message, state, 'clock')

@router.message(F.text == "🟢 24/7 Online qilish", StateFilter("*"))
async def online_24_7_service(message: Message, state: FSMContext):
    """24/7 Online qilish xizmati"""
    await state.clear()
    
    if not await require_subscription(message):
        return
    
    if not await check_referral_requirement(message):
        return
    
    await start_telegram_login(message, state, 'online')

@router.message(F.text == "🕐 Soatni o'chirish")
async def disable_clock(message: Message):
    """Soatni o'chirish"""
    user_id = message.from_user.id
    db.update_session_settings(user_id, clock_enabled=False)
    await message.answer(
        "✅ Profilga soat qo'yish o'chirildi!",
        reply_markup=kb.services_keyboard()
    )

@router.message(F.text == "🟢 Online ni o'chirish")
async def disable_online(message: Message):
    """Online ni o'chirish"""
    user_id = message.from_user.id
    db.update_session_settings(user_id, online_enabled=False)
    await message.answer(
        "✅ 24/7 Online o'chirildi!",
        reply_markup=kb.services_keyboard()
    )

@router.message(F.text == "🗑 Sessiyani o'chirish")
async def delete_session(message: Message):
    """Foydalanuvchi sessiyasini o'chirish"""
    user_id = message.from_user.id
    
    # Sessiya faylini o'chirish
    session_file = f"{SESSIONS_DIR}/user_{user_id}.session"
    if os.path.exists(session_file):
        os.remove(session_file)
    
    db.delete_user_session(user_id)
    
    await message.answer(
        "✅ Sessiya muvaffaqiyatli o'chirildi!\n\n"
        "Qayta foydalanish uchun yana login qilishingiz kerak.",
        reply_markup=kb.services_keyboard()
    )

# ============ Zaxira nusxa handlerlari ============

@router.message(F.text == "💾 Zaxira nusxa", StateFilter("*"))
async def backup_menu(message: Message, state: FSMContext):
    """Zaxira nusxa menyusi"""
    await state.clear()
    
    if not is_admin(message.from_user.id):
        await message.answer("❌ Sizda admin huquqlari yo'q!")
        return
    
    auto_backup = db.is_auto_backup_enabled()
    users_count = db.get_users_count()
    ref_count = len(db.get_all_users())  # Oddiy hisob
    
    auto_status = "🟢 Yoqilgan" if auto_backup else "🔴 O'chirilgan"
    auto_text = "\n<i>Har kuni soat 03:00 da avtomatik zaxira olinadi</i>" if auto_backup else ""
    
    text = f"💾 <b>ZAXIRA NUSXA</b>\n"
    text += f"━━━━━━━━━━━━━━━\n\n"
    text += f"📊 <b>Ma'lumotlar bazasi:</b>\n"
    text += f"├ 👥 Foydalanuvchilar: <b>{users_count}</b>\n"
    text += f"├ 📦 Referallar: <b>{db.get_referral_count(message.from_user.id)}</b>\n"
    text += f"└ 📢 Kanallar: <b>{len(db.get_active_channels())}</b>\n\n"
    text += f"⏰ <b>Avtomatik zaxira:</b> {auto_status}{auto_text}\n\n"
    text += f"📤 <b>Tiklash:</b> Zaxira faylni (.db) shu chatga yuboring"
    
    await message.answer(text, reply_markup=kb.backup_keyboard(auto_backup))

@router.message(F.text == "📥 Zaxira olish", StateFilter("*"))
async def get_backup(message: Message, state: FSMContext):
    """Zaxira olish"""
    await state.clear()
    
    if not is_admin(message.from_user.id):
        await message.answer("❌ Sizda admin huquqlari yo'q!")
        return
    
    from aiogram.types import FSInputFile
    import os
    
    db_path = "bot_database.db"
    
    if os.path.exists(db_path):
        file = FSInputFile(db_path, filename=f"backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.db")
        await message.answer_document(
            file,
            caption=f"💾 <b>Zaxira nusxa</b>\n\n"
                    f"📅 Sana: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
                    f"👥 Foydalanuvchilar: {db.get_users_count()}"
        )
    else:
        await message.answer("❌ Database fayli topilmadi!")
    
    await message.answer("Davom etish uchun tugmani tanlang:", reply_markup=kb.backup_keyboard(db.is_auto_backup_enabled()))

@router.message(F.text.startswith("⏰ Avto-zaxira:"), StateFilter("*"))
async def toggle_auto_backup(message: Message, state: FSMContext):
    """Avto-zaxirani yoqish/o'chirish"""
    await state.clear()
    
    if not is_admin(message.from_user.id):
        await message.answer("❌ Sizda admin huquqlari yo'q!")
        return
    
    new_status = db.toggle_auto_backup()
    status_text = "yoqildi ✅" if new_status else "o'chirildi ❌"
    
    await message.answer(
        f"⏰ <b>Avtomatik zaxira {status_text}</b>\n\n"
        f"{'Har kuni soat 03:00 da avtomatik zaxira olinadi.' if new_status else 'Avtomatik zaxira o`chirildi.'}",
        reply_markup=kb.backup_keyboard(new_status)
    )

@router.message(F.text == "📤 Zaxiradan tiklash", StateFilter("*"))
async def restore_backup_info(message: Message, state: FSMContext):
    """Zaxiradan tiklash haqida ma'lumot"""
    await state.clear()
    
    if not is_admin(message.from_user.id):
        await message.answer("❌ Sizda admin huquqlari yo'q!")
        return
    
    await state.set_state("waiting_backup_file")
    await message.answer(
        "📤 <b>Zaxiradan tiklash</b>\n\n"
        "⚠️ <b>Diqqat!</b> Zaxiradan tiklash joriy ma'lumotlarni o'chirib yuboradi!\n\n"
        "Zaxira faylni (.db) shu chatga yuboring yoki bekor qilish uchun pastdagi tugmani bosing:",
        reply_markup=kb.cancel_keyboard()
    )

@router.message(F.document, StateFilter("waiting_backup_file"))
async def process_backup_file(message: Message, state: FSMContext):
    """Zaxira faylini qabul qilish"""
    if not is_admin(message.from_user.id):
        await message.answer("❌ Sizda admin huquqlari yo'q!")
        return
    
    if not message.document.file_name.endswith('.db'):
        await message.answer("❌ Faqat .db formatidagi fayllarni yuklang!")
        return
    
    import os
    import shutil
    
    # Eski bazani backup qilish
    if os.path.exists("bot_database.db"):
        shutil.copy("bot_database.db", "bot_database_old.db")
    
    # Yangi faylni yuklash
    file = await bot.get_file(message.document.file_id)
    await bot.download_file(file.file_path, "bot_database.db")
    
    await state.clear()
    await message.answer(
        "✅ <b>Zaxira muvaffaqiyatli tiklandi!</b>\n\n"
        "Eski ma'lumotlar <code>bot_database_old.db</code> faylida saqlandi.",
        reply_markup=kb.backup_keyboard(db.is_auto_backup_enabled())
    )

@router.message(F.text == "🔙 Orqaga", StateFilter("*"))
async def back_to_admin_from_backup(message: Message, state: FSMContext):
    """Admin panelga qaytish"""
    await state.clear()
    
    if is_admin(message.from_user.id):
        await message.answer(
            "🔐 <b>Admin panel</b>",
            reply_markup=kb.admin_panel_reply_keyboard()
        )
    else:
        await message.answer(
            "🏠 <b>Bosh menyu</b>",
            reply_markup=kb.main_menu_keyboard()
        )

# ============ Admin panel reply button handlerlari ============

@router.message(F.text == "🏠 Bosh menyu", StateFilter("*"))
async def back_to_main_menu(message: Message, state: FSMContext):
    """Bosh menyuga qaytish"""
    await state.clear()
    await message.answer(
        "🏠 <b>Bosh menyu</b>",
        reply_markup=kb.main_menu_keyboard()
    )

@router.message(F.text == "📊 Statistika", StateFilter("*"))
async def admin_statistics(message: Message, state: FSMContext):
    """Statistika ko'rsatish"""
    await state.clear()
    
    if not is_admin(message.from_user.id):
        await message.answer("❌ Sizda admin huquqlari yo'q!")
        return
    
    users_count = db.get_users_count()
    channels = db.get_active_channels()
    
    text = f"📊 <b>Bot statistikasi</b>\n\n"
    text += f"👥 Jami foydalanuvchilar: <b>{users_count}</b>\n"
    text += f"📢 Faol kanallar: <b>{len(channels)}</b>\n"
    
    await message.answer(text, reply_markup=kb.admin_panel_reply_keyboard())

@router.message(F.text == "📢 Kanal boshqaruvi", StateFilter("*"))
async def channel_management(message: Message, state: FSMContext):
    """Kanal boshqaruvi"""
    await state.clear()
    
    if not is_admin(message.from_user.id):
        await message.answer("❌ Sizda admin huquqlari yo'q!")
        return
    
    await message.answer(
        "📢 <b>Kanal boshqaruvi</b>\n\n"
        "Quyidagi tugmalardan birini tanlang:",
        reply_markup=kb.channel_management_reply_keyboard()
    )

@router.message(F.text == "👥 Foydalanuvchilar", StateFilter("*"))
async def admin_users(message: Message, state: FSMContext):
    """Foydalanuvchilar ro'yxati"""
    await state.clear()
    
    if not is_admin(message.from_user.id):
        await message.answer("❌ Sizda admin huquqlari yo'q!")
        return
    
    users = db.get_all_users()
    
    if not users:
        await message.answer("👥 Hozircha foydalanuvchilar yo'q.", reply_markup=kb.admin_panel_reply_keyboard())
        return
    
    text = f"👥 <b>Foydalanuvchilar ro'yxati</b>\n\n"
    text += f"Jami: {len(users)} ta\n\n"
    
    for i, user in enumerate(users[:10], 1):
        name = user['first_name'] or 'Nomsiz'
        username = f"@{user['username']}" if user['username'] else ''
        text += f"{i}. {name} {username} - <code>{user['user_id']}</code>\n"
    
    if len(users) > 10:
        text += f"\n... va yana {len(users) - 10} ta"
    
    await message.answer(text, reply_markup=kb.admin_panel_reply_keyboard())

@router.message(F.text == "📨 Xabar yuborish", StateFilter("*"))
async def broadcast_start(message: Message, state: FSMContext):
    """Xabar yuborish boshlash"""
    if not is_admin(message.from_user.id):
        await message.answer("❌ Sizda admin huquqlari yo'q!")
        return
    
    await state.set_state(BroadcastState.waiting_for_message)
    await message.answer(
        "📨 <b>Xabar yuborish</b>\n\n"
        "Barcha foydalanuvchilarga yuboriladigan xabarni kiriting:",
        reply_markup=kb.cancel_keyboard()
    )

@router.message(F.text == "⬅️ Admin panelga qaytish", StateFilter("*"))
async def back_to_admin_panel(message: Message, state: FSMContext):
    """Admin panelga qaytish"""
    await state.clear()
    
    if not is_admin(message.from_user.id):
        await message.answer("❌ Sizda admin huquqlari yo'q!")
        return
    
    await message.answer(
        "🔐 <b>Admin panel</b>",
        reply_markup=kb.admin_panel_reply_keyboard()
    )

# ============ Kanal boshqaruvi handlerlari ============

@router.message(F.text == "➕ Kanal/Guruh qo'shish", StateFilter("*"))
async def add_channel_start(message: Message, state: FSMContext):
    """Kanal yoki guruh qo'shish boshlash"""
    if not is_admin(message.from_user.id):
        await message.answer("❌ Sizda admin huquqlari yo'q!")
        return
    
    await state.set_state(AddChannelState.waiting_for_channel)
    await message.answer(
        "➕ <b>Kanal yoki Guruh qo'shish</b>\n\n"
        "Kanal/guruh forward xabarini yuboring yoki ID/username kiriting.\n"
        "Masalan: @kanal_username yoki -1001234567890\n\n"
        "❗️ Bot kanal/guruhda admin bo'lishi kerak!",
        reply_markup=kb.cancel_keyboard()
    )

@router.message(F.text == "🔐 So'rovli kanal/guruh", StateFilter("*"))
async def add_request_channel_start(message: Message, state: FSMContext):
    """So'rovli kanal yoki guruh qo'shish boshlash"""
    if not is_admin(message.from_user.id):
        await message.answer("❌ Sizda admin huquqlari yo'q!")
        return
    
    await state.set_state(AddRequestChannelState.waiting_for_link)
    await message.answer(
        "🔐 <b>So'rovli kanal/guruh qo'shish</b>\n\n"
        "Kanal yoki guruh uchun yaratilgan invite havolasini yuboring.\n"
        "Masalan: https://t.me/+ABC123xyz\n\n"
        "❗️ Havola a'zo bo'lish uchun so'rov yuborish imkonini beruvchi havola bo'lishi kerak.\n"
        "❗️ Bot kanal/guruhda admin bo'lishi kerak!",
        reply_markup=kb.cancel_keyboard()
    )

@router.message(F.text == "🤖 Bot qo'shish", StateFilter("*"))
async def add_bot_start(message: Message, state: FSMContext):
    """Bot qo'shish boshlash"""
    if not is_admin(message.from_user.id):
        await message.answer("❌ Sizda admin huquqlari yo'q!")
        return
    
    await state.set_state(AddBotState.waiting_for_username)
    await message.answer(
        "🤖 <b>Bot qo'shish</b>\n\n"
        "Majburiy obunaga qo'shmoqchi bo'lgan botning username ini yuboring.\n\n"
        "Masalan: @mybot yoki mybot\n\n"
        "❗️ Foydalanuvchilar ushbu botni ishga tushirishlari kerak bo'ladi.",
        reply_markup=kb.cancel_keyboard()
    )

@router.message(AddBotState.waiting_for_username)
async def process_add_bot(message: Message, state: FSMContext):
    """Bot username ni qabul qilish"""
    if message.text == "❌ Bekor qilish":
        await state.clear()
        await message.answer("❌ Bekor qilindi", reply_markup=kb.channel_management_reply_keyboard())
        return
    
    username = message.text.strip().replace("@", "").lower()
    
    if not username.endswith("bot"):
        await message.answer(
            "❌ <b>Noto'g'ri bot username!</b>\n\n"
            "Bot username 'bot' bilan tugashi kerak.\n"
            "Masalan: @mybot, @helperbot"
        )
        return
    
    # Bot username "bot" bilan tugashini tekshirdik, endi bazaga qo'shamiz
    # Bot ID sifatida username dan hash qilamiz (bot ID ni olish imkoni yo'q)
    # Unique ID uchun username dan foydalanmiz
    bot_id = int(hashlib.md5(username.encode()).hexdigest()[:8], 16)
    
    # Bazaga qo'shish
    if db.add_channel(
        channel_id=bot_id,
        channel_username=username,
        channel_title=f"@{username}",
        added_by=message.from_user.id,
        invite_link=f"https://t.me/{username}",
        is_bot=True
    ):
        await message.answer(
            f"✅ <b>Bot muvaffaqiyatli qo'shildi!</b>\n\n"
            f"🤖 Bot: @{username}\n\n"
            f"❗️ Endi foydalanuvchilar ushbu botni /start qilishlari kerak bo'ladi.",
            reply_markup=kb.channel_management_reply_keyboard()
        )
    else:
        await message.answer(
            "❌ Bu bot allaqachon qo'shilgan!",
            reply_markup=kb.channel_management_reply_keyboard()
        )
    
    await state.clear()

@router.message(F.text == "🗑 Kanal o'chirish", StateFilter("*"))
async def delete_channel_start(message: Message, state: FSMContext):
    """Kanal o'chirish"""
    if not is_admin(message.from_user.id):
        await message.answer("❌ Sizda admin huquqlari yo'q!")
        return
    
    channels = db.get_active_channels()
    
    if not channels:
        await message.answer("📢 Hozircha kanallar yo'q.", reply_markup=kb.channel_management_reply_keyboard())
        return
    
    await state.set_state(DeleteChannelState.waiting_for_selection)
    await message.answer(
        "🗑 <b>Kanal o'chirish</b>\n\n"
        "O'chirmoqchi bo'lgan kanalni tanlang:",
        reply_markup=kb.channel_delete_keyboard(channels)
    )

@router.message(F.text == "📋 Kanallar ro'yxati", StateFilter("*"))
async def list_channels(message: Message, state: FSMContext):
    """Kanallar ro'yxati"""
    if not is_admin(message.from_user.id):
        await message.answer("❌ Sizda admin huquqlari yo'q!")
        return
    
    channels = db.get_active_channels()
    
    if not channels:
        await message.answer("📢 Hozircha kanallar yo'q.", reply_markup=kb.channel_management_reply_keyboard())
        return
    
    text = "📋 <b>Kanallar ro'yxati:</b>\n\n"
    
    for i, channel in enumerate(channels, 1):
        is_bot = channel.get('is_bot', 0)
        is_request = channel.get('is_request_channel', 0)
        
        if is_bot:
            icon = "🤖"
            type_text = "Bot"
        elif is_request:
            icon = "🔐"
            type_text = "So'rovli"
        else:
            icon = "📢"
            type_text = "Kanal"
        
        status = "✅" if channel['is_active'] else "❌"
        text += f"{i}. {icon} {status} {channel['channel_title']}\n"
        text += f"   Turi: {type_text}\n"
        text += f"   ID: <code>{channel['channel_id']}</code>\n"
        if channel['channel_username']:
            text += f"   Username: @{channel['channel_username']}\n"
        text += "\n"
    
    await message.answer(text, reply_markup=kb.channel_management_reply_keyboard())

# ============ Kanal qo'shish State handlerlari ============

@router.message(AddChannelState.waiting_for_channel)
async def process_add_channel(message: Message, state: FSMContext):
    """Kanal qo'shish"""
    if message.text == "❌ Bekor qilish":
        await state.clear()
        await message.answer("❌ Bekor qilindi.", reply_markup=kb.channel_management_reply_keyboard())
        return
    
    channel_id = None
    channel_username = None
    channel_title = None
    
    if message.forward_from_chat:
        channel_id = message.forward_from_chat.id
        channel_username = message.forward_from_chat.username
        channel_title = message.forward_from_chat.title
    else:
        text = message.text.strip()
        
        if text.startswith('@'):
            channel_username = text[1:]
            try:
                chat = await bot.get_chat(f"@{channel_username}")
                channel_id = chat.id
                channel_title = chat.title
            except Exception as e:
                await message.answer(f"❌ Kanal topilmadi: {e}", reply_markup=kb.cancel_keyboard())
                return
        elif text.startswith('-100') or text.lstrip('-').isdigit():
            channel_id = int(text)
            try:
                chat = await bot.get_chat(channel_id)
                channel_username = chat.username
                channel_title = chat.title
            except Exception as e:
                await message.answer(f"❌ Kanal/Guruh topilmadi: {e}", reply_markup=kb.cancel_keyboard())
                return
        else:
            await message.answer(
                "❌ Noto'g'ri format. Username (@kanal) yoki ID (-1001234567890) kiriting.",
                reply_markup=kb.cancel_keyboard()
            )
            return
    
    try:
        bot_member = await bot.get_chat_member(channel_id, (await bot.get_me()).id)
        if bot_member.status not in [ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.CREATOR]:
            await message.answer(
                "❌ Bot bu kanal/guruhda admin emas. Iltimos, botni admin qilib qo'shing.",
                reply_markup=kb.cancel_keyboard()
            )
            return
    except Exception as e:
        await message.answer(f"❌ Kanal/Guruh tekshirishda xato: {e}", reply_markup=kb.cancel_keyboard())
        return
    
    if db.add_channel(channel_id, channel_username, channel_title, message.from_user.id, is_request=False):
        await state.clear()
        await message.answer(
            f"✅ Muvaffaqiyatli qo'shildi!\n\n"
            f"📢 <b>{channel_title}</b>\n"
            f"🆔 <code>{channel_id}</code>",
            reply_markup=kb.channel_management_reply_keyboard()
        )
    else:
        await state.clear()
        await message.answer(
            "❌ Bu kanal/guruh allaqachon qo'shilgan!",
            reply_markup=kb.channel_management_reply_keyboard()
        )

# ============ So'rovli kanal qo'shish handlerlari ============

@router.message(AddRequestChannelState.waiting_for_link)
async def process_add_request_channel_link(message: Message, state: FSMContext):
    """So'rovli kanal qo'shish - havola qabul qilish"""
    if message.text == "❌ Bekor qilish":
        await state.clear()
        await message.answer("❌ Bekor qilindi.", reply_markup=kb.channel_management_reply_keyboard())
        return
    
    invite_link = message.text.strip()
    
    # Havola formatini tekshirish
    if not re.match(r'^https?://t\.me/\+[\w-]+$', invite_link):
        await message.answer(
            "❌ Noto'g'ri havola formati.\n\n"
            "Havola quyidagi ko'rinishda bo'lishi kerak:\n"
            "<code>https://t.me/+ABC123xyz</code>",
            reply_markup=kb.cancel_keyboard()
        )
        return
    
    await state.update_data(invite_link=invite_link)
    await state.set_state(AddRequestChannelState.waiting_for_channel_selection)
    
    await message.answer(
        "📝 <b>Kanal yoki guruh tanlang</b>\n\n"
        "Quyidagi tugmalardan birini bosing va siz admin bo'lgan kanal yoki guruhni tanlang:",
        reply_markup=kb.select_channel_keyboard()
    )

@router.message(AddRequestChannelState.waiting_for_channel_selection, F.chat_shared)
async def process_chat_shared(message: Message, state: FSMContext):
    """Kanal tanlash oynasidan tanlangan kanal"""
    chat_shared: ChatShared = message.chat_shared
    channel_id = chat_shared.chat_id
    
    data = await state.get_data()
    invite_link = data.get('invite_link')
    
    try:
        chat = await bot.get_chat(channel_id)
        channel_username = chat.username
        channel_title = chat.title
    except Exception as e:
        await message.answer(
            f"❌ Kanal/Guruh ma'lumotlarini olishda xato: {e}",
            reply_markup=kb.channel_management_reply_keyboard()
        )
        await state.clear()
        return
    
    # Botning admin ekanligini tekshirish
    try:
        bot_member = await bot.get_chat_member(channel_id, (await bot.get_me()).id)
        if bot_member.status not in [ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.CREATOR]:
            await message.answer(
                "❌ Bot bu kanal/guruhda admin emas. Iltimos, botni admin qilib qo'shing.",
                reply_markup=kb.channel_management_reply_keyboard()
            )
            await state.clear()
            return
    except Exception as e:
        await message.answer(
            f"❌ Kanal/Guruh tekshirishda xato: {e}",
            reply_markup=kb.channel_management_reply_keyboard()
        )
        await state.clear()
        return
    
    if db.add_channel(channel_id, channel_username, channel_title, message.from_user.id, is_request=True, invite_link=invite_link):
        await message.answer(
            f"✅ So'rovli kanal/guruh muvaffaqiyatli qo'shildi!\n\n"
            f"📝 <b>{channel_title}</b>\n"
            f"🆔 <code>{channel_id}</code>\n"
            f"🔗 Havola: {invite_link}",
            reply_markup=kb.channel_management_reply_keyboard()
        )
    else:
        await message.answer(
            "❌ Bu kanal/guruh allaqachon qo'shilgan!",
            reply_markup=kb.channel_management_reply_keyboard()
        )
    
    await state.clear()

@router.message(AddRequestChannelState.waiting_for_channel_selection, F.text == "❌ Bekor qilish")
async def cancel_channel_selection(message: Message, state: FSMContext):
    """Kanal/Guruh tanlashni bekor qilish"""
    await state.clear()
    await message.answer("❌ Bekor qilindi.", reply_markup=kb.channel_management_reply_keyboard())

# ============ Broadcast handlerlari ============

@router.message(BroadcastState.waiting_for_message)
async def process_broadcast_message(message: Message, state: FSMContext):
    """Broadcast xabarini qabul qilish"""
    if message.text == "❌ Bekor qilish":
        await state.clear()
        await message.answer("❌ Bekor qilindi.", reply_markup=kb.admin_panel_reply_keyboard())
        return
    
    await state.update_data(broadcast_message_id=message.message_id, broadcast_chat_id=message.chat.id)
    
    users_count = db.get_users_count()
    await message.answer(
        f"📨 Xabar {users_count} ta foydalanuvchiga yuboriladi.\n\n"
        f"Davom etish uchun 'Ha' yozing, bekor qilish uchun '❌ Bekor qilish' tugmasini bosing.",
        reply_markup=kb.cancel_keyboard()
    )
    await state.set_state(BroadcastState.confirm)

@router.message(BroadcastState.confirm)
async def confirm_broadcast(message: Message, state: FSMContext):
    """Broadcast tasdiqlash"""
    if message.text == "❌ Bekor qilish":
        await state.clear()
        await message.answer("❌ Bekor qilindi.", reply_markup=kb.admin_panel_reply_keyboard())
        return
    
    if message.text.lower() != 'ha':
        await message.answer("Tasdiqlash uchun 'Ha' yozing.")
        return
    
    data = await state.get_data()
    broadcast_message_id = data.get('broadcast_message_id')
    broadcast_chat_id = data.get('broadcast_chat_id')
    
    users = db.get_all_users()
    sent = 0
    failed = 0
    
    progress = await message.answer("📤 Xabar yuborilmoqda...")
    
    for user in users:
        try:
            await bot.copy_message(user['user_id'], broadcast_chat_id, broadcast_message_id)
            sent += 1
        except Exception as e:
            failed += 1
            logger.error(f"Xabar yuborishda xato ({user['user_id']}): {e}")
        
        if (sent + failed) % 50 == 0:
            try:
                await progress.edit_text(f"📤 Yuborilmoqda... {sent + failed}/{len(users)}")
            except:
                pass
    
    await state.clear()
    await progress.edit_text(
        f"✅ <b>Xabar yuborish yakunlandi!</b>\n\n"
        f"📤 Yuborildi: {sent}\n"
        f"❌ Xato: {failed}"
    )
    await message.answer("🔐 Admin panel", reply_markup=kb.admin_panel_reply_keyboard())

# ============ Bekor qilish handleri ============

@router.message(F.text == "❌ Bekor qilish", StateFilter("*"))
async def cancel_handler(message: Message, state: FSMContext):
    """Bekor qilish"""
    current_state = await state.get_state()
    if current_state is None:
        return
    
    await state.clear()
    
    if is_admin(message.from_user.id):
        await message.answer("❌ Bekor qilindi.", reply_markup=kb.admin_panel_reply_keyboard())
    else:
        await message.answer("❌ Bekor qilindi.", reply_markup=kb.main_menu_keyboard())

# ============ Asosiy foydalanuvchi handlerlari ============

@router.message(F.text == "👤 Mening ma'lumotlarim")
async def my_info(message: Message):
    """O'z ma'lumotlarini ko'rish"""
    if not await require_subscription(message):
        return
    
    if not await check_referral_requirement(message):
        return
    
    db.add_or_update_user(message.from_user)
    
    user_data = db.get_user(message.from_user.id)
    history = db.get_user_history(message.from_user.id)
    
    text = format_user_info(user_data, history)
    
    await message.answer(text, reply_markup=kb.user_info_keyboard(message.from_user.id))

@router.message(F.text == "🔍 Foydalanuvchi qidirish")
async def search_user_start(message: Message, state: FSMContext):
    """Foydalanuvchi qidirish"""
    if not await require_subscription(message):
        return
    
    if not await check_referral_requirement(message):
        return
    
    await state.set_state(SearchUserState.waiting_for_query)
    await message.answer(
        "🔍 <b>Foydalanuvchi qidirish</b>\n\n"
        "Foydalanuvchi ID, username yoki ismini kiriting:",
        reply_markup=kb.cancel_keyboard()
    )

@router.message(SearchUserState.waiting_for_query)
async def process_search_user(message: Message, state: FSMContext):
    """Foydalanuvchi qidirish"""
    if message.text == "❌ Bekor qilish":
        await state.clear()
        await message.answer("❌ Bekor qilindi.", reply_markup=kb.main_menu_keyboard())
        return
    
    query = message.text.strip()
    await state.clear()
    
    # ID bo'yicha qidirish
    if query.isdigit():
        user_data = db.get_user(int(query))
        if user_data:
            history = db.get_user_history(int(query))
            text = format_user_info(user_data, history)
            await message.answer(text, reply_markup=kb.user_info_keyboard(int(query)))
        else:
            await message.answer("❌ Foydalanuvchi topilmadi.", reply_markup=kb.main_menu_keyboard())
        return
    
    # Username bo'yicha qidirish
    users = db.get_all_users()
    query_lower = query.lower().replace('@', '')
    
    found = []
    for user in users:
        if (user['username'] and query_lower in user['username'].lower()) or \
           (user['first_name'] and query_lower in user['first_name'].lower()) or \
           (user['last_name'] and query_lower in user['last_name'].lower()):
            found.append(user)
    
    if not found:
        await message.answer("❌ Foydalanuvchi topilmadi.", reply_markup=kb.main_menu_keyboard())
        return
    
    if len(found) == 1:
        user_data = found[0]
        history = db.get_user_history(user_data['user_id'])
        text = format_user_info(user_data, history)
        await message.answer(text, reply_markup=kb.user_info_keyboard(user_data['user_id']))
    else:
        text = f"🔍 <b>Topildi: {len(found)} ta</b>\n\n"
        for i, user in enumerate(found[:10], 1):
            name = user['first_name'] or 'Nomsiz'
            username = f"@{user['username']}" if user['username'] else ''
            text += f"{i}. {name} {username} - <code>{user['user_id']}</code>\n"
        
        if len(found) > 10:
            text += f"\n... va yana {len(found) - 10} ta"
        
        text += "\n\nBatafsil ma'lumot uchun ID ni kiriting."
        await message.answer(text, reply_markup=kb.main_menu_keyboard())

# ============ Callback handlerlari ============

@router.callback_query(F.data == "check_subscription")
async def check_subscription_callback(callback: CallbackQuery):
    """Obunani tekshirish"""
    is_subscribed = await check_user_subscription(callback.from_user.id)
    
    if is_subscribed:
        await callback.message.delete()
        await callback.message.answer(
            f"✅ Rahmat! Endi botdan foydalanishingiz mumkin.",
            reply_markup=kb.main_menu_keyboard()
        )
    else:
        await callback.answer("❌ Siz hali barcha kanallarga obuna bo'lmadingiz!", show_alert=True)

# ============ Referal va Pul yechish callback handlerlari ============

@router.callback_query(F.data == "withdraw_money")
async def withdraw_money_callback(callback: CallbackQuery):
    """Pul yechish bo'limi"""
    user_id = callback.from_user.id
    balance_info = db.get_user_balance(user_id)
    balance = balance_info['balance']
    
    await callback.message.edit_text(
        f"💰 <b>Pul yechish</b>\n\n"
        f"💵 Joriy balansingiz: <b>{balance:,}</b> so'm\n"
        f"📤 Minimal yechish: <b>{MIN_WITHDRAWAL:,}</b> so'm\n\n"
        f"{'✅ Siz pul yechishingiz mumkin!' if balance >= MIN_WITHDRAWAL else f'❌ Pul yechish uchun yana {MIN_WITHDRAWAL - balance:,} som kerak.'}",
        reply_markup=kb.withdraw_keyboard()
    )

@router.callback_query(F.data == "start_withdraw")
async def start_withdraw_callback(callback: CallbackQuery, state: FSMContext):
    """Pul yechishni boshlash"""
    user_id = callback.from_user.id
    balance_info = db.get_user_balance(user_id)
    balance = balance_info['balance']
    
    if balance < MIN_WITHDRAWAL:
        await callback.answer(f"❌ Minimal yechish {MIN_WITHDRAWAL:,} so'm!", show_alert=True)
        return
    
    await state.set_state(WithdrawState.waiting_for_card)
    await state.update_data(amount=balance)
    await callback.message.edit_text(
        f"💳 <b>Karta raqamini kiriting</b>\n\n"
        f"💰 Yechilayotgan summa: <b>{balance:,}</b> so'm\n\n"
        f"📝 Karta raqamini 16 xonali formatda yuboring:\n"
        f"Masalan: <code>8600 1234 5678 9012</code>\n\n"
        f"❌ Bekor qilish uchun /cancel"
    )

@router.message(WithdrawState.waiting_for_card)
async def process_card_number(message: Message, state: FSMContext):
    """Karta raqamini qabul qilish"""
    if message.text == "/cancel":
        await state.clear()
        await message.answer("❌ Bekor qilindi.", reply_markup=kb.main_menu_keyboard())
        return
    
    # Karta raqamini tozalash
    card = message.text.replace(" ", "").replace("-", "")
    
    if not card.isdigit() or len(card) != 16:
        await message.answer(
            "❌ Noto'g'ri karta raqami!\n\n"
            "16 xonali karta raqamini kiriting:\n"
            "Masalan: <code>8600 1234 5678 9012</code>"
        )
        return
    
    user_id = message.from_user.id
    data = await state.get_data()
    amount = data.get('amount', 0)
    
    # Balansdan ayirish
    if not db.subtract_balance(user_id, amount):
        await state.clear()
        await message.answer("❌ Xatolik yuz berdi. Balans yetarli emas.", reply_markup=kb.main_menu_keyboard())
        return
    
    # Pul yechish so'rovini yaratish
    formatted_card = f"{card[:4]} {card[4:8]} {card[8:12]} {card[12:]}"
    withdrawal_id = db.create_withdrawal(user_id, amount, formatted_card)
    
    await state.clear()
    await message.answer(
        f"✅ <b>So'rov qabul qilindi!</b>\n\n"
        f"📋 So'rov raqami: <b>#{withdrawal_id}</b>\n"
        f"💰 Summa: <b>{amount:,}</b> so'm\n"
        f"💳 Karta: <code>{formatted_card}</code>\n\n"
        f"⏳ So'rov 24 soat ichida ko'rib chiqiladi.",
        reply_markup=kb.main_menu_keyboard()
    )
    
    # Adminlarga xabar yuborish
    for admin_id in ADMINS:
        try:
            await bot.send_message(
                admin_id,
                f"💰 <b>Yangi pul yechish so'rovi!</b>\n\n"
                f"📋 So'rov: <b>#{withdrawal_id}</b>\n"
                f"👤 Foydalanuvchi: {message.from_user.first_name} (<code>{user_id}</code>)\n"
                f"💵 Summa: <b>{amount:,}</b> so'm\n"
                f"💳 Karta: <code>{formatted_card}</code>\n\n"
                f"Admin paneldan ko'ring: /withdrawals",
                reply_markup=kb.process_withdrawal_keyboard(withdrawal_id)
            )
        except:
            pass

@router.callback_query(F.data == "my_ref_stats")
async def my_ref_stats_callback(callback: CallbackQuery):
    """Referal statistikasi"""
    user_id = callback.from_user.id
    ref_count = db.get_referral_count(user_id)
    balance_info = db.get_user_balance(user_id)
    
    await callback.message.edit_text(
        f"📊 <b>Sizning statistikangiz</b>\n\n"
        f"👥 Jami referallar: <b>{ref_count}</b> ta\n"
        f"💵 Joriy balans: <b>{balance_info['balance']:,}</b> so'm\n"
        f"💰 Jami ishlangan: <b>{balance_info['total_earned']:,}</b> so'm\n"
        f"📤 Jami yechildi: <b>{balance_info['total_withdrawn']:,}</b> so'm\n\n"
        f"💡 Har bir referal uchun <b>{REFERRAL_REWARD:,}</b> so'm olasiz!",
        reply_markup=kb.withdraw_keyboard()
    )

@router.callback_query(F.data == "back_to_referral")
async def back_to_referral_callback(callback: CallbackQuery):
    """Referalga qaytish"""
    user_id = callback.from_user.id
    ref_count = db.get_referral_count(user_id)
    balance_info = db.get_user_balance(user_id)
    bot_info = await bot.get_me()
    ref_link = f"https://t.me/{bot_info.username}?start=ref_{user_id}"
    
    balance = balance_info['balance']
    total_earned = balance_info['total_earned']
    
    status = "✅ Xizmatlarga kirish ochiq!" if ref_count >= REQUIRED_REFERRALS else f"🔒 Xizmatlarga kirish uchun yana {REQUIRED_REFERRALS - ref_count} ta referal kerak"
    
    await callback.message.edit_text(
        f"👥 <b>Referal tizimi - Pul ishlang!</b>\n\n"
        f"💰 <b>Har bir taklif uchun:</b> {REFERRAL_REWARD:,} so'm\n"
        f"📤 <b>Minimal yechish:</b> {MIN_WITHDRAWAL:,} so'm\n\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"📊 <b>Sizning statistikangiz:</b>\n"
        f"👥 Jami referallar: <b>{ref_count}</b> ta\n"
        f"💵 Joriy balans: <b>{balance:,}</b> so'm\n"
        f"💰 Jami ishlangan: <b>{total_earned:,}</b> so'm\n"
        f"━━━━━━━━━━━━━━━━━━\n\n"
        f"{status}\n\n"
        f"📎 <b>Sizning referal havolangiz:</b>\n<code>{ref_link}</code>\n\n"
        f"💡 Do'stlaringizga yuboring - ular /start bosishi bilan sizga {REFERRAL_REWARD:,} so'm tushadi!",
        reply_markup=kb.referral_keyboard(bot_info.username, user_id)
    )

# ============ Admin pul yechish boshqaruvi ============

@router.message(Command("withdrawals"))
async def admin_withdrawals(message: Message):
    """Admin: Pul yechish so'rovlarini ko'rish"""
    if not is_admin(message.from_user.id):
        return
    
    withdrawals = db.get_pending_withdrawals()
    
    if not withdrawals:
        await message.answer("✅ Kutilayotgan pul yechish so'rovlari yo'q.")
        return
    
    text = f"💰 <b>Kutilayotgan so'rovlar:</b> {len(withdrawals)} ta\n\n"
    for w in withdrawals:
        text += f"#{w['id']} - {w['first_name']} - {w['amount']:,} so'm\n"
    
    await message.answer(text, reply_markup=kb.admin_withdrawals_keyboard(withdrawals))

@router.callback_query(F.data.startswith("view_withdrawal_"))
async def view_withdrawal_callback(callback: CallbackQuery):
    """Pul yechish so'rovini ko'rish"""
    if not is_admin(callback.from_user.id):
        return
    
    withdrawal_id = int(callback.data.replace("view_withdrawal_", ""))
    w = db.get_withdrawal_by_id(withdrawal_id)
    
    if not w:
        await callback.answer("So'rov topilmadi!", show_alert=True)
        return
    
    await callback.message.edit_text(
        f"💰 <b>Pul yechish so'rovi #{w['id']}</b>\n\n"
        f"👤 User ID: <code>{w['user_id']}</code>\n"
        f"💵 Summa: <b>{w['amount']:,}</b> so'm\n"
        f"💳 Karta: <code>{w['card_number']}</code>\n"
        f"📅 Yaratilgan: {w['created_at'][:16]}\n"
        f"📊 Status: {w['status']}",
        reply_markup=kb.process_withdrawal_keyboard(withdrawal_id)
    )

@router.callback_query(F.data.startswith("approve_withdrawal_"))
async def approve_withdrawal_callback(callback: CallbackQuery):
    """Pul yechish so'rovini tasdiqlash"""
    if not is_admin(callback.from_user.id):
        return
    
    withdrawal_id = int(callback.data.replace("approve_withdrawal_", ""))
    w = db.get_withdrawal_by_id(withdrawal_id)
    
    if not w:
        await callback.answer("So'rov topilmadi!", show_alert=True)
        return
    
    db.process_withdrawal(withdrawal_id, "approved")
    
    await callback.message.edit_text(
        f"✅ <b>So'rov #{withdrawal_id} tasdiqlandi!</b>\n\n"
        f"💵 {w['amount']:,} so'm\n"
        f"💳 {w['card_number']}"
    )
    
    # Foydalanuvchiga xabar
    try:
        await bot.send_message(
            w['user_id'],
            f"✅ <b>Pul yechish so'rovingiz tasdiqlandi!</b>\n\n"
            f"💵 Summa: <b>{w['amount']:,}</b> so'm\n"
            f"💳 Karta: <code>{w['card_number']}</code>\n\n"
            f"Pul tez orada kartangizga o'tkaziladi!"
        )
    except:
        pass

@router.callback_query(F.data.startswith("reject_withdrawal_"))
async def reject_withdrawal_callback(callback: CallbackQuery):
    """Pul yechish so'rovini rad etish"""
    if not is_admin(callback.from_user.id):
        return
    
    withdrawal_id = int(callback.data.replace("reject_withdrawal_", ""))
    w = db.get_withdrawal_by_id(withdrawal_id)
    
    if not w:
        await callback.answer("So'rov topilmadi!", show_alert=True)
        return
    
    # Pulni qaytarish
    db.add_balance(w['user_id'], w['amount'])
    db.process_withdrawal(withdrawal_id, "rejected")
    
    await callback.message.edit_text(
        f"❌ <b>So'rov #{withdrawal_id} rad etildi!</b>\n\n"
        f"💵 {w['amount']:,} so'm foydalanuvchiga qaytarildi."
    )
    
    # Foydalanuvchiga xabar
    try:
        await bot.send_message(
            w['user_id'],
            f"❌ <b>Pul yechish so'rovingiz rad etildi!</b>\n\n"
            f"💵 Summa: <b>{w['amount']:,}</b> so'm balansingizga qaytarildi.\n\n"
            f"Sabab: Admin tomonidan rad etildi."
        )
    except:
        pass

@router.callback_query(F.data.startswith("history_"))
async def show_history(callback: CallbackQuery):
    """O'zgarishlar tarixini ko'rsatish"""
    user_id = int(callback.data.split("_")[1])
    history = db.get_user_history(user_id)
    
    if not history:
        await callback.answer("📜 O'zgarishlar tarixi yo'q.", show_alert=True)
        return
    
    text = f"📜 <b>O'zgarishlar tarixi</b>\n\n"
    
    for h in history[:15]:
        field_names = {
            'first_name': 'Ism',
            'last_name': 'Familiya',
            'username': 'Username',
            'phone_number': 'Telefon'
        }
        field = field_names.get(h['field_name'], h['field_name'])
        text += f"📅 {h['changed_at']}\n"
        text += f"   {field}: <code>{h['old_value'] or 'Bo`sh'}</code> → <code>{h['new_value'] or 'Bo`sh'}</code>\n\n"
    
    if len(history) > 15:
        text += f"... va yana {len(history) - 15} ta o'zgarish"
    
    await callback.message.answer(text)
    await callback.answer()

@router.callback_query(F.data.startswith("groups_"))
async def show_groups(callback: CallbackQuery):
    """Guruhlarni ko'rsatish"""
    user_id = int(callback.data.split("_")[1])
    groups = db.get_user_groups(user_id)
    
    if not groups:
        await callback.answer("👥 Guruhlar topilmadi.", show_alert=True)
        return
    
    text = f"👥 <b>Foydalanuvchi guruhlari</b>\n\n"
    
    for g in groups[:10]:
        text += f"📌 {g['group_title']}\n"
        text += f"   ID: <code>{g['group_id']}</code>\n"
        if g['group_username']:
            text += f"   Username: @{g['group_username']}\n"
        text += f"   Birinchi ko'rish: {g['first_seen']}\n\n"
    
    if len(groups) > 10:
        text += f"... va yana {len(groups) - 10} ta guruh"
    
    await callback.message.answer(text)
    await callback.answer()

@router.callback_query(F.data.startswith("delete_"), DeleteChannelState.waiting_for_selection)
async def delete_channel_callback(callback: CallbackQuery, state: FSMContext):
    """Kanalni o'chirish"""
    channel_id = callback.data.split("_")[1]
    
    if db.remove_channel(channel_id):
        await callback.message.edit_text("✅ Kanal muvaffaqiyatli o'chirildi!")
    else:
        await callback.message.edit_text("❌ Kanalni o'chirishda xato.")
    
    await state.clear()
    await callback.message.answer("📢 Kanal boshqaruvi", reply_markup=kb.channel_management_reply_keyboard())

# ============ Guruh handlerlari ============

@router.message(F.chat.type.in_({ChatType.GROUP, ChatType.SUPERGROUP}))
async def group_message_handler(message: Message):
    """Guruhdagi xabarlarni qayta ishlash"""
    if message.from_user:
        db.add_or_update_user(message.from_user)
        db.add_user_to_group(
            message.from_user.id,
            message.chat.id,
            message.chat.title,
            message.chat.username
        )

# ============ Join request handleri ============

@router.chat_join_request()
async def handle_join_request(event):
    """Kanalga qo'shilish so'rovini qayta ishlash"""
    user_id = event.from_user.id
    chat_id = event.chat.id
    
    # So'rovni database ga saqlash
    db.add_join_request(user_id, chat_id)
    
    logger.info(f"Join request: user {user_id} -> channel {chat_id}")

# ============ Kontakt handleri ============

@router.message(F.contact)
async def contact_handler(message: Message):
    """Telefon raqamini qabul qilish"""
    if message.contact.user_id == message.from_user.id:
        db.update_user_phone(message.from_user.id, message.contact.phone_number)
        await message.answer(
            f"✅ Telefon raqamingiz saqlandi: {message.contact.phone_number}",
            reply_markup=kb.main_menu_keyboard()
        )
    else:
        await message.answer("❌ Faqat o'z telefon raqamingizni yuborishingiz mumkin.")

# ============ Background Tasks ============

async def update_user_clocks():
    """Foydalanuvchi profillariga soat qo'yish"""
    while True:
        try:
            sessions = db.get_active_clock_sessions()
            
            for session in sessions:
                try:
                    # Foydalanuvchining API ma'lumotlarini ishlatish
                    user_api_id = int(session.get('api_id', 0))
                    user_api_hash = session.get('api_hash', '')
                    
                    if not user_api_id or not user_api_hash:
                        logger.warning(f"No API credentials for user {session['user_id']}")
                        continue
                    
                    client = Client(
                        name=f"clock_{session['user_id']}",
                        api_id=user_api_id,
                        api_hash=user_api_hash,
                        session_string=session['session_string']
                    )
                    
                    async with client:
                        # Hozirgi vaqtni olish
                        now = datetime.now()
                        clock_emojis = ["🕛", "🕐", "🕑", "🕒", "🕓", "🕔", "🕕", "🕖", "🕗", "🕘", "🕙", "🕚"]
                        hour = now.hour % 12
                        current_clock = clock_emojis[hour]
                        time_str = now.strftime("%H:%M")
                        
                        # Foydalanuvchi ma'lumotlarini olish
                        me = await client.get_me()
                        new_last_name = f"{current_clock} {time_str}"
                        
                        # Profilni yangilash
                        await client.update_profile(last_name=new_last_name)
                        logger.info(f"Clock updated for user {session['user_id']}: {new_last_name}")
                        
                except Exception as e:
                    logger.error(f"Clock update error for {session['user_id']}: {e}")
                    
            # Har daqiqada yangilash
            await asyncio.sleep(60)
            
        except Exception as e:
            logger.error(f"Clock task error: {e}")
            await asyncio.sleep(60)

async def keep_users_online():
    """Foydalanuvchilarni online saqlash"""
    while True:
        try:
            sessions = db.get_active_online_sessions()
            
            for session in sessions:
                try:
                    # Foydalanuvchining API ma'lumotlarini ishlatish
                    user_api_id = int(session.get('api_id', 0))
                    user_api_hash = session.get('api_hash', '')
                    
                    if not user_api_id or not user_api_hash:
                        logger.warning(f"No API credentials for user {session['user_id']}")
                        continue
                    
                    client = Client(
                        name=f"online_{session['user_id']}",
                        api_id=user_api_id,
                        api_hash=user_api_hash,
                        session_string=session['session_string']
                    )
                    
                    async with client:
                        # Online statusni yangilash
                        await client.invoke(
                            __import__('pyrogram.raw.functions', fromlist=['account']).account.UpdateStatus(
                                offline=False
                            )
                        )
                        logger.info(f"Online status updated for user {session['user_id']}")
                        
                except Exception as e:
                    logger.error(f"Online update error for {session['user_id']}: {e}")
                    
            # Har 5 daqiqada yangilash
            await asyncio.sleep(300)
            
        except Exception as e:
            logger.error(f"Online task error: {e}")
            await asyncio.sleep(300)

# ============ Ishga tushirish ============

async def main():
    db.init_database()
    logger.info("Bot ishga tushirildi!")
    
    # Background tasklarni ishga tushirish
    asyncio.create_task(update_user_clocks())
    asyncio.create_task(keep_users_online())
    
    await dp.start_polling(bot, skip_updates=True)

if __name__ == "__main__":
    asyncio.run(main())
