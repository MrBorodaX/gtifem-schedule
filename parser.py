import asyncio
import os
import requests
import hashlib
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
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID: return
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
    if not os.path.exists(filepath): return None
    with open(filepath, 'rb') as f: return hashlib.md5(f.read()).hexdigest()

async def select_value(page, text):
    """Выбор значения через JavaScript"""
    try:
        result = await page.evaluate(f"""
            () => {{
                const targetText = '{text}';
                const allElements = Array.from(document.querySelectorAll('*'));
                const matches = allElements.filter(el => 
                    el.textContent && el.textContent.trim() === targetText
                );
                
                if (matches.length === 0) {{
                    const partialMatches = allElements.filter(el => 
                        el.textContent && targetText.toLowerCase().includes(el.textContent.trim().toLowerCase())
                    );
                    if (partialMatches.length > 0) {{
                        partialMatches[0].scrollIntoView({{behavior: 'auto', block: 'center'}});
                        partialMatches[0].click();
                        return true;
                    }}
                    return false;
                }}
                
                matches[0].scrollIntoView({{behavior: 'auto', block: 'center'}});
                matches[0].click();
                return true;
            }}
        """)
        
        if result:
            print(f"✅ Выбрано: {text}")
            await page.wait_for_timeout(800)
    except Exception as e:
        print(f"⚠️ Ошибка при выборе '{text}': {e}")

async def main():
    print("🚀 Запуск умного парсера...")
    
    current_month, current_year = get_current_month_and_year()
    print(f"📅 Парсим месяц: {current_month} {current_year} года")
    
    old_hash = get_file_hash('schedule.ics')
    
    events_data = []
    html = ""
    
    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page()
            await page.goto("https://gtifem.ru/dekanat/raspisanie/", timeout=30000)
            await page.wait_for_load_state("networkidle")
            await page.wait_for_timeout(2000)
            
            # Последовательно выбираем все параметры
            targets = [DEPARTMENT, MAJOR, COURSE, GROUP, current_month]
            for text in targets:
                await select_value(page, text)
                await page.wait_for_timeout(1000)
            
            print("Ожидаем появления таблицы...")
            await page.wait_for_selector("table", timeout=10000)
            await page.wait_for_timeout(2000)
            
            html = await page.content()
            await browser.close()
            
    except Exception as e:
        print(f"❌ Ошибка браузера: {e}")
        with open('schedule.ics', 'wb') as f:
            f.write(b"BEGIN:VCALENDAR\nVERSION:2.0\nPRODID:-//GTIFEM//RU\nEND:VCALENDAR")
        return

    soup = BeautifulSoup(html, 'html.parser')
    
    # Ищем ВСЕ ячейки с data-group (это и есть пары)
    schedule_cells = soup.find_all('td', attrs={'data-group': True})
    print(f"📊 Найдено ячеек с расписанием: {len(schedule_cells)}")
    
    for cell in schedule_cells:
        try:
            # Получаем данные из атрибутов
            data_day = cell.get('data-day', '')
            data_time = cell.get('data-time', '')
            data_month = cell.get('data-month', current_month)
            
            # Пропускаем пустые ячейки
            if not data_day or not data_time:
                continue
            
            # Извлекаем предмет, аудиторию и преподавателя из div'ов
            subject_div = cell.find('div', class_='subject')
            aud_div = cell.find('div', class_='aud')
            
            # Получаем текст
            subject = subject_div.get_text(strip=True) if subject_div else ""
            
            # Аудитория может быть в <b> внутри div.aud
            if aud_div:
                b_tag = aud_div.find('b')
                room = b_tag.get_text(strip=True) if b_tag else aud_div.get_text(strip=True)
            else:
                room = ""
            
            # Преподаватель - это div после .aud (но не .number)
            teacher = ""
            for div in cell.find_all('div'):
                if div.get('class') and 'aud' in div.get('class'):
                    # Следующий sibling - преподаватель
                    next_div = div.find_next_sibling('div')
                    if next_div and (not next_div.get('class') or 'number' not in next_div.get('class', [])):
                        teacher = next_div.get_text(strip=True)
                    break
            
            # Пропускаем пустые или специальные ячейки
            if not subject or subject in [". .", ""]:
                continue
            
            # Парсим время (формат: "16:00 - 17:40")
            time_parts = data_time.replace(' ', '').split('-')
            if len(time_parts) != 2:
                continue
            
            t_start = time_parts[0]
            t_end = time_parts[1]
            
            # Определяем день месяца
            day = int(data_day)
            month_map = {
                'сентября': '09', 'октября': '10', 'ноября': '11', 'декабря': '12',
                'января': '01', 'февраля': '02', 'марта': '03', 'апреля': '04', 'мая': '05', 'июня': '06'
            }
            month_num = month_map.get(data_month.lower(), '09')
            date_fmt = f"{day:02d}.{month_num}.{current_year}"
            
            events_data.append({
                "date": date_fmt,
                "time_start": t_start,
                "time_end": t_end,
                "subject": subject,
                "room": room,
                "teacher": teacher
            })
            
        except Exception as e:
            print(f"⚠️ Ошибка парсинга ячейки: {e}")
            continue

    print(f"📚 Найдено пар: {len(events_data)}")

    # Создаем ICS
    cal = Calendar()
    cal.add('prodid', '-//GTIFEM Schedule//RU')
    cal.add('version', '2.0')
    tz = pytz.timezone('Europe/Moscow')
    
    for ev in events_data:
        try:
            event = Event()
            event.add('summary', ev['subject'])
            event.add('location', ev['room'])
            event.add('description', ev['teacher'])
            
            start_dt = tz.localize(datetime.strptime(f"{ev['date']} {ev['time_start']}", "%d.%m.%Y %H:%M"))
            end_dt = tz.localize(datetime.strptime(f"{ev['date']} {ev['time_end']}", "%d.%m.%Y %H:%M"))
            
            event.add('dtstart', start_dt)
            event.add('dtend', end_dt)
            cal.add_component(event)
        except Exception as e:
            print(f"️ Ошибка создания события: {e}")
            continue

    new_ics_data = cal.to_ical()
    new_hash = hashlib.md5(new_ics_data).hexdigest()
    
    if old_hash == new_hash:
        print("✅ Расписание не изменилось.")
    else:
        print("🔥 Обнаружены изменения!")
        with open('schedule.ics', 'wb') as f:
            f.write(new_ics_data)
        send_telegram(f"🚨 <b>Деканат изменил расписание!</b>\n\nГруппа: {GROUP}\nМесяц: {current_month.title()}\nПар: {len(events_data)}")

if __name__ == "__main__":
    asyncio.run(main())
