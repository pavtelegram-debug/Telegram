import json_repair

import aiofiles
import asyncio
import logging
import random
import json
import os
import urllib.request

from aiogram import Bot, Dispatcher, types, F
from aiogram.filters.command import Command

BOT_TOKEN = os.getenv('BOT_TOKEN', '').strip()
if not BOT_TOKEN:
    raise RuntimeError('BOT_TOKEN environment variable is not configured')

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

channels = [('TeleFost News', 'http://t.me/TeleFost')]

async def get_numbers() -> dict:
    try:
        async with aiofiles.open('numbers.json', 'r', encoding='utf-8') as file:
            data = json_repair.loads(await file.read())
            return data if isinstance(data, dict) else {}
    except FileNotFoundError:
        await write_numbers({})
        return {}

async def write_numbers(numbers: dict) -> None:
    # топовый способ хранения номеров 2026
    async with aiofiles.open('numbers.json', 'w') as file:
        await file.write(json.dumps(numbers))
    
async def has_free_number(uid: str | int) -> bool:
    numbers = await get_numbers()
    for number in numbers.get(str(uid), []):
        if number.startswith('79'):
            return True
            
    return False

async def create_user(uid: str | int) -> None:
    numbers = await get_numbers()
    if str(uid) in numbers:
        return
    
    numbers.update({str(uid): numbers.get(str(uid)) or []})
    await write_numbers(numbers)

async def is_number_exists(number: str) -> bool:
    numbers = await get_numbers()
    return any(number in user_numbers for user_numbers in numbers.values() for number in user_numbers)
    
async def add_free_number(uid: str | int) -> str:
    numbers = await get_numbers()
    phone = f'79{random.randint(100_000_000, 999_999_999)}'
    if await is_number_exists(phone):
        return await add_free_number(uid)
    
    numbers[str(uid)].append(phone)

    await write_numbers(numbers)
    return phone

async def add_anon_number(uid: str | int) -> str:
    numbers = await get_numbers()
    phone = f'79{random.randint(100_000_000, 999_999_999)}'
    if await is_number_exists(phone):
        return await add_anon_number(uid)
    
    numbers[str(uid)].append(phone)

    await write_numbers(numbers)
    return phone

async def add_short_anon(uid: str | int) -> str:
    numbers = await get_numbers()
    phone = f'79{random.randint(100_000_000, 999_999_999)}'
    if await is_number_exists(phone):
        return await add_short_anon(uid)

    numbers[str(uid)].append(phone)

    await write_numbers(numbers)
    return phone

async def sync_number_with_api(number: str, owner: int) -> bool:
    """Register the number with Telefost API using a secret stored in the environment."""
    api_url = os.getenv('TELEFOST_API_URL', 'https://telefost-api.onrender.com').rstrip('/')
    api_key = os.getenv('TELEFOST_BOT_API_KEY', '').strip()
    if not api_key:
        logging.error('TELEFOST_BOT_API_KEY is not configured; API sync skipped')
        return False

    payload = json.dumps({'number': '+' + number, 'owner': int(owner)}).encode('utf-8')
    request = urllib.request.Request(
        api_url + '/v1/bot/numbers',
        data=payload,
        method='POST',
        headers={'Content-Type': 'application/json', 'X-Telefost-Bot-Key': api_key},
    )

    def send_request() -> bool:
        try:
            with urllib.request.urlopen(request, timeout=10) as response:
                result = json.loads(response.read().decode('utf-8'))
            return bool(result.get('ok'))
        except Exception:
            logging.exception('Could not sync assigned number with Telefost API')
            return False

    return await asyncio.to_thread(send_request)


@dp.message(Command('start'))
async def start(message: types.Message) -> None:
    keyboard = types.InlineKeyboardMarkup(inline_keyboard=[])
    for channel in channels:
        member = await bot.get_chat_member(channel[1].replace('http://t.me/', '@'), message.from_user.id)
        if member.status == 'left':
            keyboard.inline_keyboard.append([types.InlineKeyboardButton(text=f'📢 {channel[0]}', url=channel[1])])

    if any(keyboard.inline_keyboard):
        keyboard.inline_keyboard.append([types.InlineKeyboardButton(text='✅ Я подписался', url='http://t.me/telefostauth_bot?start=1')])
        await message.answer('<b>🕹 Подпишись на следующие каналы для продолжения работы с ботом.</b>', parse_mode='HTML', reply_markup=keyboard)
        return

    keyboard = types.InlineKeyboardMarkup(
        inline_keyboard=[
            [types.InlineKeyboardButton(text='📱 Получить бесплатный номер', callback_data='freenum')],
            [types.InlineKeyboardButton(text='📱 Купить анонимный номер', callback_data='anon')],
            [types.InlineKeyboardButton(text='📱 Купить короткий анонимный номер', callback_data='shortanon')],
            [types.InlineKeyboardButton(text='📊 Мои номера', callback_data='mynums')]
        ]
    )

    await message.answer('<b>👋 Привет! Это бот для авторизации в Telefost.</b>\n\nℹ️ Здесь ты можешь приобрести анонимный номер за звезды, либо взять бесплатный номер. Все коды, отправленные в Telefost на приобретенные тобой номера, будут отображаться здесь.\n\n<b>🕹 Используй кнопки ниже для управления ботом.</b>', parse_mode='HTML', reply_markup=keyboard)

@dp.callback_query(F.data == 'freenum')
async def freenum(query: types.CallbackQuery) -> None:
    await create_user(query.from_user.id)

    if await has_free_number(query.from_user.id):
        await query.message.answer('<b>❌ У вас уже есть бесплатный номер!</b>', parse_mode='HTML')
        await query.answer()
        return
    
    number = await add_free_number(query.from_user.id)
    synced = await sync_number_with_api(number, query.from_user.id)
    suffix = '' if synced else '\n\n⚠️ Номер создан, но синхронизация с API не подтверждена.'
    await query.message.answer(f'<b>✅ Успешно добавлен бесплатный номер!\n\n📱 Номер:</b><pre>+{number}</pre>{suffix}', parse_mode='HTML')
    await query.answer()

@dp.callback_query(F.data == 'anon')
async def anon(query: types.CallbackQuery) -> None:
    await query.message.answer_invoice(
        title='📱 Анонимный номер\n', 
        description='ℹ️ Анонимный номер для входа в Voidgram. Пример: +79XXXXXXXXX',
        prices=[
            types.LabeledPrice(label='Оплата', amount=100)
        ],
        payload='anon',
        currency='XTR'
    )

    await query.answer()

@dp.callback_query(F.data == 'shortanon')
async def shortanon(query: types.CallbackQuery) -> None:
    await query.message.answer_invoice(
        title='📱 Короткий анонимный номер', 
        description='ℹ️ Короткий анонимный номер для входа в Voidgram. Пример: +79XXXXXXXXX',
        prices=[
            types.LabeledPrice(label='Оплата', amount=200)
        ],
        payload='shortanon',
        currency='XTR'
    )

    await query.answer()

@dp.callback_query(F.data == 'mynums')
async def mynums(query: types.CallbackQuery) -> None:
    numbers = await get_numbers()
    if not numbers.get(str(query.from_user.id)):
        await query.message.answer('<b>❌ У вас нет номеров.</b>', parse_mode='HTML')
        await query.answer()
        return
    
    numbers_list = []

    for i, number in enumerate(numbers[str(query.from_user.id)]):
        numbers_list.append(f'{i + 1}. <code>+{number}</code>')
    
    await query.message.answer(f'<b>📱 Список ваших номеров</b>\n\n{"\n".join(numbers_list)}', parse_mode='HTML')
    await query.answer()

@dp.pre_checkout_query(F.invoice_payload == 'anon')
async def anon_payment(query: types.PreCheckoutQuery) -> None:
    await query.answer(ok=True)

@dp.pre_checkout_query(F.invoice_payload == 'shortanon')
async def shortanon_payment(query: types.PreCheckoutQuery) -> None:
    await query.answer(ok=True)

@dp.message(F.successful_payment)
async def process_successful_payment(message: types.Message) -> None:
    payload = message.successful_payment.invoice_payload
    await create_user(message.from_user.id)

    if payload == 'anon':
        number = await add_anon_number(message.from_user.id)
        synced = await sync_number_with_api(number, message.from_user.id)
        suffix = '' if synced else '\n\n⚠️ Номер создан, но синхронизация с API не подтверждена.'
        await message.answer(f'<b>✅ Успешно добавлен анонимный номер!\n\n📱 Номер:</b><pre>+{number}</pre>{suffix}', parse_mode='HTML')
    elif payload == 'shortanon':
        number = await add_short_anon(message.from_user.id)
        synced = await sync_number_with_api(number, message.from_user.id)
        suffix = '' if synced else '\n\n⚠️ Номер создан, но синхронизация с API не подтверждена.'
        await message.answer(f'<b>✅ Успешно добавлен короткий анонимный номер!\n\n📱 Номер:</b><pre>+{number}</pre>{suffix}', parse_mode='HTML')

# а еще в этом сурсе всратая оплата звездами и типы с экстера плагином могут бесплатно покупать кучу анонок
# или я успел пофиксить эту хуйню ну не знаю крч
# думайте

async def main() -> None:
    logging.basicConfig(level=logging.INFO)
    await dp.start_polling(bot)

if __name__ == '__main__':
    asyncio.run(main())