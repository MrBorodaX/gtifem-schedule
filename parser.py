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
        1: "Январь", 2: "Февраль", 3: "Март", 4: "Апрель", 5: "Май", 6: "Июнь",
        9: "Сентябрь", 10: "Октябрь", 11: "Ноябрь", 12: "Декабрь"
    }
    month_name = months_ru.get(month_num, "Сентябрь")
    year = now.year if month_num >= 9 else now.year + 1
    return month_name, year

def get_file_hash(filepath):
    if not os.path.exists(filepath): return None
    with open(filepath, 'rb') as f: return hashlib.md5(f.read()).hexdigest()

async def open_dropdown(page, index):
    """Открывает dropdown по индексу (0 - отделение, 1 - направление, 2 - курс, 3 - группа, 4 - месяц)"""
    try:
        # Находим все dropdown контейнеры (обычно это div с классом .select или .dropdown)
        dropdowns = await page.locator(".select, .dropdown, select").all()
        if index < len(dropdowns):
            await dropdowns[index].click(timeout=3000)
            await page.wait_for_timeout(500)
            print(f"✅ Dropdown #{index} открыт")
    except Exception as e:
        print(f"⚠️ Не удалось открыть dropdown #{index}: {e}")

async def select_option(page, text, dropdown_index=None):
    """Выбирает опцию из dropdown"""
    try:
        # Если указан индекс dropdown, сначала открываем его
        if dropdown_index is not None:
            await open_dropdown(page, dropdown_index)
        
        # Попытка 1: Стандартный select
        try:
            await page.locator("select").select_option(label=text, timeout=2000)
            print(f"✅ Выбрано (select): {text}")
            return
        except:
            pass
        
        # Попытка 2: Клик по тексту с force=True
        await page.get_by_text(text, exact=True).first.click(force=True, timeout=5000)
        await page.wait_for_timeout(800)
        print(f"✅ Выбрано (force click): {text}")
    except Exception as e:
        print(f"⚠️ Не удалось выбрать '{text}': {e}")

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
            
            # Последовательно открываем dropdowns и выбираем опции
            print(f"Выбираем отделение: {DEPARTMENT}")
            await select_option(page, DEPARTMENT, dropdown_index=0)
            
            print(f"Выбираем направление: {MAJOR}")
            await select_option(page, MAJOR, dropdown_index=1)
            
            print(f"Выбираем курс: {COURSE}")
            await select_option(page, COURSE, dropdown_index=2)
            
            print(f"Выбираем группу: {GROUP}")
            await select_option(page, GROUP, dropdown_index=3)
            
            print(f"Выбираем месяц: {current_month}")
            await select_option(page, current_month, dropdown_index=4)
            
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

    for row_idx, row in enumerate(rows):
        cells = row.find_all(['td', 'th'])
        cell_texts = [c.get_text(strip=True) for c in cells]
        
        if len(cell_texts) > 1 and any("а." in text or text == ". ." for text in cell_texts[1:]):
            if row_idx > 0 and row_idx < len(rows) - 1:
                prev_cells = rows[row_idx - 1].find_all(['td', 'th'])
                next_cells = rows[row_idx + 1].find_all(['td', 'th'])
                
                time_text = cells[0].get_text(strip=True)
                if "-" not in time_text and len(prev_cells) > 0:
                    time_text = prev_cells[0].get_text(strip=True)
                
                for col_idx, (date_idx, date_name) in enumerate(date_cols):
                    target_idx = col_idx + 1
                    
                    if target_idx < len(cells) and target_idx < len(prev_cells) and target_idx < len(next_cells):
                        subject = prev_cells[target_idx].get_text(strip=True)
                        room = cells[target_idx].get_text(strip=True)
                        teacher = next_cells[target_idx].get_text(strip=True)
                        
                        if subject and subject not in [". .", ""] and room not in [". .", ""]:
                            events_data.append({
                                "date": date_name, "time": time_text,
                                "subject": subject, "room": room, "teacher": teacher
                            })

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
        except:
            continue

    new_ics_data = cal.to_ical()
    new_hash = hashlib.md5(new_ics_data).hexdigest()
    
    if old_hash == new_hash:
        print("✅ Расписание не изменилось.")
    else:
        print("🔥 Обнаружены изменения! Сохраняем и уведомляем.")
        with open('schedule.ics', 'wb') as f:
            f.write(new_ics_data)
        send_telegram(f"🚨 <b>Деканат изменил расписание!</b>\n\nГруппа: {GROUP}\nМесяц: {current_month}\nПар: {len(events_data)}")

if __name__ == "__main__":
    asyncio.run(main())
