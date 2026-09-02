import asyncio
import os
import requests
import hashlib
import re
from datetime import datetime
from playwright.async_api import async_playwright
from bs4 import BeautifulSoup
from icalendar import Calendar, Event
import pytz

# === ВАШИ НАСТРОЙКИ ===
DEPARTMENT = "Бакалавриат"
MAJOR = "Логистика"
COURSE = "1 курс"
GROUP = "6661"

TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
TELEGRAM_CHAT_ID = os.getenv('TELEGRAM_CHAT_ID')

def send_telegram(message):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    try:
        requests.post(url, data={"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "HTML"})
    except Exception as e:
        print(f"Ошибка Telegram: {e}")

def get_current_month_and_year():
    now = datetime.now()
    month_num = now.month
    months_ru = {
        1: "января", 2: "февраля", 3: "марта", 4: "апреля", 5: "мая", 6: "июня",
        9: "сентября", 10: "октября", 11: "ноября", 12: "декабря"
    }
    month_name = months_ru.get(month_num, "сентября")
    year = now.year if month_num >= 9 else now.year + 1
    return month_name, year

def get_file_hash(filepath):
    if not os.path.exists(filepath):
        return None
    with open(filepath, 'rb') as f:
        return hashlib.md5(f.read()).hexdigest()

async def js_click_by_text(page, text):
    """Клик через чистый JS - обходит все проверки видимости"""
    try:
        result = await page.evaluate(f"""
            () => {{
                const target = '{text}';
                const elements = Array.from(document.querySelectorAll('a'));
                const match
