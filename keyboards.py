# -*- coding: utf-8 -*-
from aiogram.types import (
    ReplyKeyboardMarkup, KeyboardButton,
    InlineKeyboardMarkup, InlineKeyboardButton,
    KeyboardButtonRequestChat, ChatAdministratorRights
)


def main_menu_keyboard():
    keyboard = ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="🗂 Xizmatlar")],
            [KeyboardButton(text="👥 Referal"), KeyboardButton(text="🆘 Qo'llab-quvvatlash")]
        ],
        resize_keyboard=True
    )
    return keyboard


def services_keyboard():
    keyboard = ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="👤 Mening ma'lumotlarim"), KeyboardButton(text="🔍 Foydalanuvchi qidirish")],
            [KeyboardButton(text="📱 Telefon raqamini aniqlash"), KeyboardButton(text="🕐 Profilga soat qo'yish")],
            [KeyboardButton(text="🟢 24/7 Online qilish")],
            [KeyboardButton(text="⬅️ Orqaga")]
        ],
        resize_keyboard=True
    )
    return keyboard


def admin_panel_reply_keyboard():
    keyboard = ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📊 Statistika"), KeyboardButton(text="📢 Kanal boshqaruvi")],
            [KeyboardButton(text="👥 Foydalanuvchilar"), KeyboardButton(text="📨 Xabar yuborish")],
            [KeyboardButton(text="💾 Zaxira nusxa")],
            [KeyboardButton(text="🏠 Bosh menyu")]
        ],
        resize_keyboard=True
    )
    return keyboard


def backup_keyboard(auto_backup_enabled=False):
    """Zaxira nusxa boshqaruvi tugmalari"""
    status = "🟢" if auto_backup_enabled else "🔴"
    keyboard = ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📥 Zaxira olish")],
            [KeyboardButton(text=f"⏰ Avto-zaxira: {status}")],
            [KeyboardButton(text="📤 Zaxiradan tiklash")],
            [KeyboardButton(text="🔙 Orqaga")]
        ],
        resize_keyboard=True
    )
    return keyboard


def channel_management_reply_keyboard():
    keyboard = ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="➕ Kanal/Guruh qo'shish"), KeyboardButton(text="🔐 So'rovli kanal/guruh")],
            [KeyboardButton(text="🤖 Bot qo'shish"), KeyboardButton(text="🗑 Kanal o'chirish")],
            [KeyboardButton(text="📋 Kanallar ro'yxati")],
            [KeyboardButton(text="⬅️ Admin panelga qaytish")]
        ],
        resize_keyboard=True
    )
    return keyboard


def cancel_keyboard():
    keyboard = ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="❌ Bekor qilish")]],
        resize_keyboard=True
    )
    return keyboard


def select_channel_keyboard():
    keyboard = ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(
                text="📢 Kanal tanlash",
                request_chat=KeyboardButtonRequestChat(
                    request_id=1,
                    chat_is_channel=True,
                    bot_is_member=True
                )
            )],
            [KeyboardButton(
                text="👥 Guruh tanlash",
                request_chat=KeyboardButtonRequestChat(
                    request_id=2,
                    chat_is_channel=False,
                    bot_is_member=True
                )
            )],
            [KeyboardButton(text="❌ Bekor qilish")]
        ],
        resize_keyboard=True,
        one_time_keyboard=True
    )
    return keyboard


def check_subscription_keyboard(channels):
    buttons = []
    for channel in channels:
        username = channel['channel_username']
        is_request = channel.get('is_request_channel', 0)
        is_bot = channel.get('is_bot', 0)
        invite_link = channel.get('invite_link', '')
        url = None
        
        if is_bot:
            # Bot uchun
            url = f"https://t.me/{username.replace('@', '')}?start=check"
            button_text = "🤖 Botni ishga tushirish"
        elif is_request:
            if invite_link:
                url = invite_link
            elif username:
                url = f"https://t.me/{username.replace('@', '')}"
            button_text = "➕ Kanalga obuna bo'lish"
        else:
            if username:
                url = f"https://t.me/{username.replace('@', '')}"
            elif invite_link:
                url = invite_link
            button_text = "➕ Kanalga obuna bo'lish"
        
        if url:
            buttons.append([InlineKeyboardButton(text=button_text, url=url)])
    buttons.append([InlineKeyboardButton(text="✅ Tekshirish", callback_data="check_subscription")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def referral_keyboard(bot_username, user_id):
    ref_link = f"https://t.me/{bot_username}?start=ref_{user_id}"
    share_url = f"https://t.me/share/url?url={ref_link}"
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📤 Havolani ulashish", url=share_url)],
        [InlineKeyboardButton(text="💰 Pul yechish", callback_data="withdraw_money")],
        [InlineKeyboardButton(text="📊 Statistika", callback_data="my_ref_stats")]
    ])
    return keyboard


def withdraw_keyboard():
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💳 Pul yechish", callback_data="start_withdraw")],
        [InlineKeyboardButton(text="⬅️ Orqaga", callback_data="back_to_referral")]
    ])
    return keyboard


def admin_withdrawals_keyboard(withdrawals):
    buttons = []
    for w in withdrawals:
        buttons.append([InlineKeyboardButton(
            text=f"#{w['id']} - {w['first_name']} - {w['amount']} so'm",
            callback_data=f"view_withdrawal_{w['id']}"
        )])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def process_withdrawal_keyboard(withdrawal_id):
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ Tasdiqlash", callback_data=f"approve_withdrawal_{withdrawal_id}"),
            InlineKeyboardButton(text="❌ Rad etish", callback_data=f"reject_withdrawal_{withdrawal_id}")
        ]
    ])
    return keyboard


def channel_delete_keyboard(channels):
    buttons = []
    for channel in channels:
        buttons.append([InlineKeyboardButton(text=f"🗑 {channel['channel_title']}", callback_data=f"delete_{channel['channel_id']}")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def user_info_keyboard(user_id):
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="📜 O'zgarishlar tarixi", callback_data=f"history_{user_id}"),
            InlineKeyboardButton(text="👥 Guruhlar", callback_data=f"groups_{user_id}")
        ]
    ])
    return keyboard


def clock_control_keyboard():
    """Soat xizmati boshqaruvi"""
    keyboard = ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="🕐 Soatni o'chirish")],
            [KeyboardButton(text="🗑 Sessiyani o'chirish")],
            [KeyboardButton(text="⬅️ Orqaga")]
        ],
        resize_keyboard=True
    )
    return keyboard


def online_control_keyboard():
    """Online xizmati boshqaruvi"""
    keyboard = ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="🟢 Online ni o'chirish")],
            [KeyboardButton(text="🗑 Sessiyani o'chirish")],
            [KeyboardButton(text="⬅️ Orqaga")]
        ],
        resize_keyboard=True
    )
    return keyboard
