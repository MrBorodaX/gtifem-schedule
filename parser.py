import asyncio
import os
import requests
import hashlib
import re
from datetime import datetime
from collections import defaultdict
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
    """Отправка уведомления в Telegram с отладкой"""
    print(f"📤 Попытка отправить в Telegram: {TELEGRAM_BOT_TOKEN[:10] if TELEGRAM_BOT_TOKEN else 'None'}... / {TELEGRAM_CHAT_ID}")
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print(" Telegram токены не настроены!")
        return False
    
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    data = {"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "HTML"}
    
    try:
        response = requests.post(url, data=data, timeout=10)
        if response.status_code == 200:
            print("✅ Уведомление отправлено успешно")
            return True
        else:
            print(f" Ошибка Telegram API: {response.status_code} - {response.text}")
            return False
    except Exception as e:
        print(f"❌ Ошибка отправки: {e}")
        return False

def get_current_month_and_year():
    now = datetime.now()
    month_num = now.month
    months_ui = {
        1: "январь", 2: "февраль", 3: "март", 4: "апрель", 5: "май", 6: "июнь",
        9: "сентябрь", 10: "октябрь", 11: "ноябрь", 12: "декабрь"
    }
    ui_name = months_ui.get(month_num, "сентябрь")
    year = now.year if month_num >= 9 else now.year + 1
    return ui_name, year

def get_file_hash(filepath):
    if not os.path.exists(filepath):
        return None
    with open(filepath, 'rb') as f:
        return hashlib.md5(f.read()).hexdigest()

def parse_subject_name(subject_full):
    """
    Парсит название предмета и тип занятия
    Пример: "Основы российской государственности (лек)" → ("Основы российской государственности", "ЛЕК")
    """
    match = re.search(r'\((лек|пр|лаб)\)', subject_full, re.IGNORECASE)
    if match:
        subject_type = match.group(1).upper()
        subject_name = subject_full[:match.start()].strip()
        return subject_name, subject_type
    return subject_full, ""

async def js_click_by_text(page, text):
    """Клик через чистый JS"""
    try:
        result = await page.evaluate("""
            (target) => {
                const elements = Array.from(document.querySelectorAll('a'));
                const match = elements.find(el => el.textContent.trim().toLowerCase() === target.toLowerCase() && el.offsetParent !== null);
                if (match) {
                    match.click();
                    return true;
                }
                const anyMatch = elements.find(el => el.textContent.trim().toLowerCase() === target.toLowerCase());
                if (anyMatch) {
                    anyMatch.click();
                    return true;
                }
                return false;
            }
        """, text)
        if result:
            print(f"✅ Клик: {text}")
        else:
            print(f"⚠️ Не найден: {text}")
        return result
    except Exception as e:
        print(f"❌ Ошибка клика '{text}': {e}")
        return False

async def wait_for_visible_elements(page, selector, timeout=10000):
    """Ждет появления видимых элементов"""
    try:
        await page.wait_for_function("""
            (sel) => {
                const elements = document.querySelectorAll(sel);
                return Array.from(elements).some(el => el.offsetParent !== null);
            }
        """, selector, timeout=timeout)
        return True
    except:
        return False

async def main():
    print(" Запуск умного парсера...")
    
    current_month_ui, current_year = get_current_month_and_year()
    print(f"📅 Парсим месяц: {current_month_ui} {current_year} года")
    
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
            
            await page.evaluate("""
                () => {
                    document.querySelectorAll('.sc-widget, .cookie-banner, .modal, .popup').forEach(el => el.remove());
                }
            """)
            print("✅ Баннеры удалены")
            
            print("Выбираем отделение...")
            await js_click_by_text(page, DEPARTMENT)
            await page.wait_for_timeout(1500)
            
            print("Выбираем направление...")
            await js_click_by_text(page, MAJOR)
            await wait_for_visible_elements(page, ".section.courses ul li a", timeout=10000)
            print("✅ Курсы загружены")
            await page.wait_for_timeout(1500)
            
            print("Выбираем курс...")
            await js_click_by_text(page, COURSE)
            await wait_for_visible_elements(page, ".section.groups ul li a", timeout=10000)
            print("✅ Группы загружены")
            await page.wait_for_timeout(1500)
            
            print("Выбираем группу...")
            await js_click_by_text(page, GROUP)
            await wait_for_visible_elements(page, ".section.months ul li a", timeout=10000)
            print("✅ Месяцы загружены")
            await page.wait_for_timeout(1500)
            
            print(f"Выбираем месяц: {current_month_ui}...")
            await js_click_by_text(page, current_month_ui)
            await page.wait_for_selector("table", timeout=15000)
            print("✅ Таблица появилась")
            await page.wait_for_timeout(3000)
            
            html = await page.content()
            await browser.close()
            
    except Exception as e:
        print(f"❌ Критическая ошибка: {e}")
        with open('schedule.ics', 'wb') as f:
            f.write(b"BEGIN:VCALENDAR\nVERSION:2.0\nPRODID:-//GTIFEM//RU\nEND:VCALENDAR")
        return

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
    if not table:
        print("❌ Таблица не найдена")
        return
    
    schedule_cells = table.find_all('td', attrs={'data-group': True})
    print(f"🔍 Найдено ячеек: {len(schedule_cells)}")
    
    # Собираем все события в словарь по датам
    events_by_date = defaultdict(list)
    
    for cell in schedule_cells:
        try:
            cell_text = cell.get_text(strip=True)
            data_day = cell.get('data-day', '')
            data_time = cell.get('data-time', '')
            data_month_attr = cell.get('data-month', current_month_ui)
            
            subject_div = cell.find('div', class_='subject')
            aud_div = cell.find('div', class_='aud')
            
            subject_full = subject_div.get_text(strip=True) if subject_div else ""
            
            room = ""
            if aud_div:
                b_tag = aud_div.find('b')
                room = b_tag.get_text(strip=True) if b_tag else aud_div.get_text(strip=True)
            
            teacher = ""
            if aud_div:
                next_div = aud_div.find_next_sibling('div')
                if next_div and (not next_div.get('class') or 'number' not in next_div.get('class', [])):
                    teacher = next_div.get_text(strip=True)
            
            if not subject_full or subject_full in [". .", ""]:
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
                'января': '01', 'февраля': '02', 'марта': '03', 'апреля': '04', 'мая': '05', 'июня': '06',
                'сентябрь': '09', 'октябрь': '10', 'ноябрь': '11', 'декабрь': '12',
                'январь': '01', 'февраль': '02', 'март': '03', 'апрель': '04', 'май': '05', 'июнь': '06'
            }
            month_num = month_map.get(data_month_attr.lower(), '09')
            date_fmt = f"{day:02d}.{month_num}.{current_year}"
            
            # Парсим название предмета и тип
            subject_name, subject_type = parse_subject_name(subject_full)
            
            events_by_date[date_fmt].append({
                "time_start": t_start,
                "time_end": t_end,
                "subject_name": subject_name,
                "subject_type": subject_type,
                "room": room,
                "teacher": teacher
            })
        except Exception as e:
            print(f"⚠️ Ошибка парсинга ячейки: {e}")
            continue
    
    # Для каждой даты сортируем события по времени и присваиваем номера по порядку
    final_events = []
    for date_fmt, day_events in events_by_date.items():
        # Сортируем по времени начала
        day_events.sort(key=lambda x: x['time_start'])
        
        # Присваиваем номера по порядку (1, 2, 3...)
        for slot_number, event in enumerate(day_events, start=1):
            # Формируем название: "1. ЛЕК Основы российской государственности"
            if event['subject_type']:
                event_title = f"{slot_number}. {event['subject_type']} {event['subject_name']}"
            else:
                event_title = f"{slot_number}. {event['subject_name']}"
            
            final_events.append({
                "date": date_fmt,
                "time_start": event['time_start'],
                "time_end": event['time_end'],
                "title": event_title,
                "room": event['room'],
                "teacher": event['teacher']
            })
    
    print(f"📚 Найдено уникальных пар: {len(final_events)}")

    cal = Calendar()
    cal.add('prodid', '-//GTIFEM Schedule//RU')
    cal.add('version', '2.0')
    tz = pytz.timezone('Europe/Moscow')
    
    for ev in final_events:
        try:
            event = Event()
            event.add('summary', ev['title'])
            event.add('location', ev['room'])
            event.add('description', ev['teacher'])
            
            start_dt = tz.localize(datetime.strptime(f"{ev['date']} {ev['time_start']}", "%d.%m.%Y %H:%M"))
            end_dt = tz.localize(datetime.strptime(f"{ev['date']} {ev['time_end']}", "%d.%m.%Y %H:%M"))
            
            event.add('dtstart', start_dt)
            event.add('dtend', end_dt)
            cal.add_component(event)
        except Exception as e:
            print(f"⚠️ Ошибка создания события: {e}")
            continue

    new_ics_data = cal.to_ical()
    new_hash = hashlib.md5(new_ics_data).hexdigest()
    
    if old_hash == new_hash:
        print("✅ Расписание не изменилось.")
        send_telegram(f"✅ <b>Проверка расписания</b>\n\nГруппа: {GROUP}\nМесяц: {current_month_ui.capitalize()}\nПар: {len(final_events)}\n\nИзменений нет.")
    else:
        print("🔥 Обнаружены изменения!")
        with open('schedule.ics', 'wb') as f:
            f.write(new_ics_data)
        send_telegram(f"🚨 <b>Деканат изменил расписание!</b>\n\nГруппа: {GROUP}\nМесяц: {current_month_ui.capitalize()}\nПар: {len(final_events)}\n\nGoogle Календарь обновится в течение 24 часов.")

if __name__ == "__main__":
    asyncio.run(main())
