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

async def select_from_dropdown(page, section_class, value_text):
    """
    Выбирает значение из кастомного dropdown
    section_class: 'groups', 'months' и т.д.
    value_text: текст для выбора (например, '6661' или 'сентября')
    """
    try:
        # Находим секцию dropdown
        section = page.locator(f".section.{section_class}").first
        
        # Кликаем по заголовку, чтобы открыть список
        title = section.locator(".title").first
        await title.click()
        await page.wait_for_timeout(500)
        
        # Ищем нужный элемент в списке
        list_items = section.locator("ul li a")
        count = await list_items.count()
        
        for i in range(count):
            item = list_items.nth(i)
            text = await item.inner_text()
            if value_text.lower() in text.lower():
                await item.click()
                await page.wait_for_timeout(800)
                print(f"✅ Выбрано из {section_class}: {value_text}")
                return
        
        print(f"⚠️ Не найдено '{value_text}' в {section_class}")
    except Exception as e:
        print(f"⚠️ Ошибка при выборе {section_class} '{value_text}': {e}")

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
            
            # Выбираем из dropdowns
            # Примечание: на сайте gtifem.ru структура может отличаться
            # Если dropdowns с отделением/направлением/курсом работают иначе,
            # используем force click для них
            
            # Для группы и месяца используем новую функцию
            await select_from_dropdown(page, "groups", GROUP)
            await select_from_dropdown(page, "months", current_month)
            
            print("Ожидаем появления таблицы...")
            await page.wait_for_selector("table", timeout=15000)
            html = await page.content()
            await browser.close()
            
    except Exception as e:
        print(f"❌ Ошибка браузера: {e}")
        with open('schedule.ics', 'wb') as f:
            f.write(b"BEGIN:VCALENDAR\nVERSION:2.0\nPRODID:-//GTIFEM//RU\nEND:VCALENDAR")
        return

    soup = BeautifulSoup(html, 'html.parser')
    table = soup.find('table')
    if not table:
        print("❌ Таблица не найдена")
        with open('schedule.ics', 'wb') as f:
            f.write(b"BEGIN:VCALENDAR\nVERSION:2.0\nPRODID:-//GTIFEM//RU\nEND:VCALENDAR")
        return

    rows = table.find_all('tr')
    headers = [th.get_text(strip=True) for th in rows[0].find_all(['th', 'td'])]
    date_cols = []
    for i, h in enumerate(headers):
        if any(m in h.lower() for m in ['сентября', 'октября', 'ноября', 'декабря', 'января', 'февраля', 'марта', 'апреля', 'мая', 'июня']):
            date_cols.append((i, h))

    print(f"📅 Найдено колонок с датами: {len(date_cols)}")
    
    # Парсим матричную структуру таблицы (как в Excel)
    for row_idx, row in enumerate(rows):
        cells = row.find_all(['td', 'th'])
        cell_texts = [c.get_text(strip=True) for c in cells]
        
        # Ищем строки с аудиториями (содержат "а." или ". .")
        if len(cell_texts) > 1 and any("а." in text or text == ". ." for text in cell_texts[1:]):
            if row_idx > 0 and row_idx < len(rows) - 1:
                prev_cells = rows[row_idx - 1].find_all(['td', 'th'])  # Предметы
                next_cells = rows[row_idx + 1].find_all(['td', 'th'])  # Преподаватели
                
                # Время берем из первой колонки
                time_text = cells[0].get_text(strip=True)
                if "-" not in time_text and len(prev_cells) > 0:
                    time_text = prev_cells[0].get_text(strip=True)
                
                # Проходим по всем колонкам с датами
                for col_idx, (date_idx, date_name) in enumerate(date_cols):
                    target_idx = col_idx + 1  # +1, так как 0-я колонка это время
                    
                    if target_idx < len(cells) and target_idx < len(prev_cells) and target_idx < len(next_cells):
                        subject = prev_cells[target_idx].get_text(strip=True)
                        room = cells[target_idx].get_text(strip=True)
                        teacher = next_cells[target_idx].get_text(strip=True)
                        
                        # Игнорируем пустые ячейки
                        if subject and subject not in [". .", ""] and room not in [". .", ""]:
                            events_data.append({
                                "date": date_name, "time": time_text,
                                "subject": subject, "room": room, "teacher": teacher
                            })

    print(f"📊 Найдено пар: {len(events_data)}")

    # Создаем ICS
    cal = Calendar()
    cal.add('prodid', '-//GTIFEM Schedule//RU')
    cal.add('version', '2.0')
    tz = pytz.timezone('Europe/Moscow')
    
    month_map = {
        'сентября': '09', 'октября': '10', 'ноября': '11', 'декабря': '12',
        'января': '01', 'февраля': '02', 'марта': '03', 'апреля': '04', 'мая': '05', 'июня': '06'
    }
    
    for ev in events_data:
        try:
            event = Event()
            event.add('summary', ev['subject'])
            event.add('location', ev['room'])
            event.add('description', ev['teacher'])
            
            parts = ev['date'].split()
            if len(parts) >= 2:
                day = parts[0].zfill(2)
                month_name = parts[1].lower()
                month = month_map.get(month_name, '09')
                date_fmt = f"{day}.{month}.{current_year}"
                
                time_clean = ev['time'].replace(' ', '').replace('\n', '')
                if '-' in time_clean:
                    t_start, t_end = time_clean.split('-')
                else:
                    continue
                
                start_dt = tz.localize(datetime.strptime(f"{date_fmt} {t_start}", "%d.%m.%Y %H:%M"))
                end_dt = tz.localize(datetime.strptime(f"{date_fmt} {t_end}", "%d.%m.%Y %H:%M"))
                
                event.add('dtstart', start_dt)
                event.add('dtend', end_dt)
                cal.add_component(event)
        except Exception as e:
            print(f"⚠️ Ошибка парсинга: {e}")
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

if __name__ == "__main__":
    asyncio.run(main())
