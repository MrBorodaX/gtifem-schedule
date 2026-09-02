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
            
            # Удаляем баннер cookie
            try:
                await page.evaluate("""
                    () => {
                        document.querySelectorAll('.sc-widget, .cookie-banner').forEach(el => el.remove());
                    }
                """)
                print("✅ Баннер cookie удален")
            except:
                pass
            
            # ШАГ 1: Кликаем по "Бакалавриат" (он виден сразу)
            print("Выбираем отделение...")
            await page.click("text=Бакалавриат", timeout=10000)
            await page.wait_for_timeout(1500)
            print("✅ Бакалавриат выбран")
            
            # ШАГ 2: Ждем появления секции "Направление" и кликаем по "Логистика"
            print("Выбираем направление...")
            await page.wait_for_selector(".section.specials", state="visible", timeout=10000)
            await page.click("text=Логистика", timeout=10000)
            await page.wait_for_timeout(1500)
            print("✅ Логистика выбрана")
            
            # ШАГ 3: Ждем появления секции "Курс" и кликаем по "1 курс"
            print("Выбираем курс...")
            await page.wait_for_selector(".section.courses", state="visible", timeout=10000)
            # Для курса нужно кликнуть по первому "1 курс" в видимой секции
            await page.locator(".section.courses a:has-text('1 курс')").first.click(timeout=10000)
            await page.wait_for_timeout(1500)
            print("✅ 1 курс выбран")
            
            # ШАГ 4: Ждем появления секции "Группа" и заполнения списка
            print("Выбираем группу...")
            await page.wait_for_selector(".section.groups", state="visible", timeout=10000)
            # Ждем, пока список групп заполнится
            await page.wait_for_selector(".section.groups ul li", timeout=10000)
            await page.wait_for_timeout(1000)
            # Кликаем по группе 6661
            await page.click("text=6661", timeout=10000)
            await page.wait_for_timeout(1500)
            print("✅ Группа 6661 выбрана")
            
            # ШАГ 5: Ждем появления секции "Месяц" и кликаем по нужному месяцу
            print("Выбираем месяц...")
            await page.wait_for_selector(".section.months", state="visible", timeout=10000)
            await page.wait_for_selector(".section.months ul li", timeout=10000)
            await page.wait_for_timeout(1000)
            # Кликаем по месяцу (например, "сентября")
            await page.click(f"text={current_month}", timeout=10000)
            await page.wait_for_timeout(1500)
            print(f"✅ {current_month} выбран")
            
            # ШАГ 6: Ждем появления таблицы расписания
            print("⏳ Ожидаем загрузки таблицы...")
            await page.wait_for_selector("table", timeout=15000)
            await page.wait_for_timeout(3000)  # Дополнительное время на полную отрисовку
            
            html = await page.content()
            await browser.close()
            
    except Exception as e:
        print(f" Ошибка: {e}")
        with open('debug.html', 'w', encoding='utf-8') as f:
            f.write(html if html else "")
        with open('schedule.ics', 'wb') as f:
            f.write(b"BEGIN:VCALENDAR\nVERSION:2.0\nPRODID:-//GTIFEM//RU\nEND:VCALENDAR")
        return

    # Проверяем загрузку
    if GROUP not in html:
        print("❌ Расписание не загрузилось.")
        with open('debug.html', 'w', encoding='utf-8') as f:
            f.write(html)
        soup = BeautifulSoup(html, 'html.parser')
        body_text = soup.body.get_text(separator=' ', strip=True) if soup.body else ""
        print(f"🔍 ТЕКСТ:\n{body_text[:1000]}")
        with open('schedule.ics', 'wb') as f:
            f.write(b"BEGIN:VCALENDAR\nVERSION:2.0\nPRODID:-//GTIFEM//RU\nEND:VCALENDAR")
        return

    print("✅ Данные найдены!")
    soup = BeautifulSoup(html, 'html.parser')
    
    table = soup.find('table')
    if table:
        schedule_cells = table.find_all('td', attrs={'data-group': True})
        if not schedule_cells:
            schedule_cells = table.find_all('td')
    else:
        schedule_cells = []

    print(f"🔍 Найдено ячеек: {len(schedule_cells)}")
    
    for cell in schedule_cells:
        try:
            cell_text = cell.get_text(strip=True)
            data_day = cell.get('data-day', '')
            data_time = cell.get('data-time', '')
            data_month_attr = cell.get('data-month', current_month)
            
            subject_div = cell.find('div', class_='subject')
            aud_div = cell.find('div', class_='aud')
            
            subject = subject_div.get_text(strip=True) if subject_div else ""
            
            room = ""
            if aud_div:
                b_tag = aud_div.find('b')
                room = b_tag.get_text(strip=True) if b_tag else aud_div.get_text(strip=True)
            
            teacher = ""
            if aud_div:
                next_div = aud_div.find_next_sibling('div')
                if next_div and (not next_div.get('class') or 'number' not in next_div.get('class', [])):
                    teacher = next_div.get_text(strip=True)
            
            if not subject or subject in [". .", ""]:
                continue
            
            time_parts = data_time.replace(' ', '').split('-') if data_time else []
            if len(time_parts) == 2:
                t_start, t_end = time_parts[0], time_parts[1]
            else:
                time_match = re.search(r'(\d{2}:\d{2})\s*-\s*(\d{2}:\d{2})', cell_text)
                if time_match:
                    t_start, t_end = time_match.groups()
                else:
                    continue
            
            day = int(data_day) if data_day.isdigit() else 1
            month_map = {
                'сентября': '09', 'октября': '10', 'ноября': '11', 'декабря': '12',
                'января': '01', 'февраля': '02', 'марта': '03', 'апреля': '04', 'мая': '05', 'июня': '06'
            }
            month_num = month_map.get(data_month_attr.lower(), '09')
            date_fmt = f"{day:02d}.{month_num}.{current_year}"
            
            events_data.append({
                "date": date_fmt,
                "time_start": t_start,
                "time_end": t_end,
                "subject": subject,
                "room": room,
                "teacher": teacher
            })
        except Exception:
            continue

    # Удаляем дубликаты
    unique_events = []
    seen = set()
    for ev in events_data:
        key = (ev['date'], ev['time_start'], ev['subject'])
        if key not in seen:
            seen.add(key)
            unique_events.append(ev)
    
    events_data = unique_events
    print(f"📚 Найдено уникальных пар: {len(events_data)}")

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
            print(f"⚠️ Ошибка: {e}")
            continue

    new_ics_data = cal.to_ical()
    new_hash = hashlib.md5(new_ics_data).hexdigest()
    
    if old_hash == new_hash:
        print("✅ Расписание не изменилось.")
    else:
        print(" Обнаружены изменения!")
        with open('schedule.ics', 'wb') as f:
            f.write(new_ics_data)
        send_telegram(f"🚨 <b>Деканат изменил расписание!</b>\n\nГруппа: {GROUP}\nМесяц: {current_month.title()}\nПар: {len(events_data)}")

if __name__ == "__main__":
    asyncio.run(main())
