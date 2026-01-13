# 🤖 Tahlilchi Bot

Foydalanuvchi ma'lumotlarini tahlil qiluvchi Telegram bot.

## 📋 Imkoniyatlar

- 👤 **Foydalanuvchi ma'lumotlari** - ism, familya, ID, username, telefon
- 📜 **Tarix** - barcha o'zgarishlar saqlanadi (ism, username almashtirganda)
- 👥 **Guruhlar** - foydalanuvchi qaysi guruhlarda borligi
- 📢 **Majburiy obuna** - kanallar boshqaruvi
- ⚙️ **Admin panel** - to'liq boshqaruv

## 🚀 O'rnatish

### 1. Kerakli kutubxonalarni o'rnatish

```bash
pip install -r requirements.txt
```

### 2. Bot tokenini sozlash

`config.py` faylini oching va quyidagilarni to'ldiring:

```python
BOT_TOKEN = "YOUR_BOT_TOKEN_HERE"  # @BotFather dan olingan token
ADMINS = [123456789]  # O'zingizning Telegram ID raqamingiz
```

### 3. Botni ishga tushirish

```bash
python main.py
```

## 📁 Fayl strukturasi

```
tahlilchi bot/
├── config.py          # Sozlamalar
├── database.py        # Database funksiyalari
├── keyboards.py       # Tugmalar
├── main.py           # Asosiy bot fayli
├── requirements.txt  # Kerakli kutubxonalar
└── README.md         # Hujjat
```

## 🔧 Foydalanish

### Oddiy foydalanuvchilar uchun:
- `/start` - Botni ishga tushirish
- "👤 Mening ma'lumotlarim" - O'z ma'lumotlarini ko'rish
- "🔍 Foydalanuvchi qidirish" - ID bo'yicha qidirish
- Forward xabar yuborish - Foydalanuvchi ma'lumotlarini olish

### Admin uchun:
- "⚙️ Admin panel" - Admin panelga kirish
- "📢 Kanal boshqaruvi" - Kanallarni qo'shish/o'chirish
- "👥 Foydalanuvchilar" - Barcha foydalanuvchilar ro'yxati
- "📊 Statistika" - Batafsil statistika

## 📢 Kanal qo'shish

1. Botni kanalga admin qiling
2. Admin paneldan "📢 Kanal boshqaruvi" ni tanlang
3. "➕ Kanal qo'shish" tugmasini bosing
4. Kanal username yoki ID ni yuboring

## ⚠️ Muhim

- Bot guruhga qo'shilganda, guruh a'zolari haqida ma'lumot yig'adi
- Forward qilingan xabarlardan foydalanuvchi ID sini olish mumkin
- Foydalanuvchi telefon raqamini kontakt sifatida yuborishi kerak

## 📞 Aloqa

Muammolar yoki takliflar bo'lsa, admin bilan bog'laning.
