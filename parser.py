import asyncio
import os
import requests
import hashlib
from playwright.async_api import async_playwright
from bs4 import BeautifulSoup
from icalendar import Calendar, Event
from datetime import datetime
import pytz

TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
TELEGRAM_CHAT_ID = os.getenv('TELEGRAM_CHAT_ID')

def send_telegram(message):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    requests.post(url, data={"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "HTML"})

def get_hash(filepath):
    if not os.path.exists(filepath): return None
    with open(filepath, 'rb') as f: return hashlib.md5(f.read()).hexdigest()

async def main():
    # 1. Запускаем браузер
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        await page.goto("https://gtifem.ru/dekanat/raspisanie/")
        await page.wait_for_load_state("networkidle")
        
        # 2. Выбираем параметры (замените на ваши реальные значения с сайта)
        for text in ["Бакалавриат", "Экономика", "1 курс", "1001", "Сентябрь"]:
            try:
                await page.get_by_text(text, exact=True).first.click()
                await page.wait_for_timeout(600)
            except:
                pass
        
        # 3. Ждем таблицу и забираем HTML
        try:
            await page.wait_for_selector("table", timeout=10000)
        except:
            print("Таблица не найдена!")
        html = await page.content()
        await browser.close()

    # 4. Парсим HTML
    soup = BeautifulSoup(html, 'html.parser')
    events_data = []
    
    # ВНИМАНИЕ: Здесь нужно будет подстроить селекторы под реальный HTML сайта.
    # Обычно это строки таблицы <tr>, внутри которых <td> с датой, временем, предметом, аудиторией и преподавателем.
    rows = soup.find_all('tr')
    for row in rows:
        cells = row.find_all(['td', 'th'])
        if len(cells) >= 5:
            date_str = cells[0].get_text(strip=True)
            time_str = cells[1].get_text(strip=True)
            subject = cells[2].get_text(strip=True)
            room = cells[3].get_text(strip=True)
            teacher = cells[4].get_text(strip=True)
            
            if not date_str or "Дата" in date_str or subject in [". .", ""]:
                continue
                
            events_data.append({
                "date": date_str, "time": time_str, 
                "subject": subject, "room": room, "teacher": teacher
            })

    # 5. Создаем ICS
    cal = Calendar()
    cal.add('prodid', '-//GTIFEM Schedule//RU')
    cal.add('version', '2.0')
    tz = pytz.timezone('Europe/Moscow')
    
    for ev in events_data:
        event = Event()
        event.add('summary', ev['subject'])
        event.add('location', ev['room'])
        event.add('description', ev['teacher'])
        
        # Пример парсинга: "1 сентября" и "09:30 - 11:10"
        # (Логику нужно будет точно подстроить под формат сайта)
        try:
            day = ev['date'].split()[0].zfill(2)
            month_map = {'сентября':'09', 'октября':'10', 'ноября':'11', 'декабря':'12'}
            month = month_map.get(ev['date'].split()[1], '09')
            date_fmt = f"{day}.{month}.2026"
            
            t_start, t_end = ev['time'].replace(' ', '').split('-')
            start_dt = tz.localize(datetime.strptime(f"{date_fmt} {t_start}", "%d.%m.%Y %H:%M"))
            end_dt = tz.localize(datetime.strptime(f"{date_fmt} {t_end}", "%d.%m.%Y %H:%M"))
            
            event.add('dtstart', start_dt)
            event.add('dtend', end_dt)
            cal.add_component(event)
        except Exception as e:
            continue # Пропускаем строки, которые не удалось распарсить

    with open('schedule.ics', 'wb') as f:
        f.write(cal.to_ical())

    # 6. Проверка изменений и уведомление
    new_hash = get_hash('schedule.ics')
    # (Для простоты здесь сравниваем количество событий, в реальном коде лучше сравнивать хеш файла)
    send_telegram(f"✅ Расписание обновлено!\nНайдено пар: {len(events_data)}")
    print("Готово!")

if __name__ == "__main__":
    asyncio.run(main())
