import asyncio
import os
import requests
import hashlib
import re
import json
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

MONTHS_ORDER = [
    "сентябрь", "октябрь", "ноябрь", "декабрь",
    "январь", "февраль", "март", "апрель", "май", "июнь"
]

def send_telegram(message):
    print(f"📤 Отправка в Telegram...")
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("⚠️ Токены Telegram не найдены!")
        return False
    
    # Разделяем строку с ID по запятой и убираем лишние пробелы
    chat_ids = [cid.strip() for cid in TELEGRAM_CHAT_ID.split(',')]
    
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    data = {"text": message, "parse_mode": "HTML"}
    
    success_count = 0
    for chat_id in chat_ids:
        data["chat_id"] = chat_id
        try:
            response = requests.post(url, data=data, timeout=10)
            if response.status_code == 200:
                print(f"✅ Уведомление успешно отправлено пользователю {chat_id}")
                success_count += 1
            else:
                print(f"❌ Ошибка API для {chat_id}: {response.status_code} - {response.text}")
        except Exception as e:
            print(f"❌ Ошибка сети для {chat_id}: {e}")
            
    return success_count > 0

def get_semester_months():
    now = datetime.now()
    month_num = now.month
    
    if 9 <= month_num <= 12:
        start_idx = 0
        end_idx = 3
        year = now.year
    elif 1 <= month_num <= 6:
        start_idx = 4
        end_idx = 9
        year = now.year + 1
    else:
        start_idx = 0
        end_idx = 3
        year = now.year
    
    months = []
    for idx in range(start_idx, end_idx + 1):
        month_name = MONTHS_ORDER[idx]
        if idx < 4:
            month_year = year
        else:
            month_year = year + 1
        months.append((month_name, month_year))
    
    return months

def parse_subject_name(subject_full):
    match = re.search(r'\((лек|пр|лаб)\)', subject_full, re.IGNORECASE)
    if match:
        return subject_full[:match.start()].strip(), match.group(1).upper()
    return subject_full, ""

def extract_teacher_from_cell(cell):
    """
    Извлекает имя преподавателя из ячейки.
    В HTML преподаватель находится как текстовый узел между </div> (aud) и <div class="number">
    Пример: </div>\n  "Воронов А. А."\n  <div class="number">
    """
    cell_html = str(cell)
    # Ищем текст между закрывающим </div> блока aud и открывающим <div class="number">
    match = re.search(r'<div class="aud">.*?</div>\s*(.*?)\s*<div class="number">', cell_html, re.DOTALL)
    if match:
        teacher = match.group(1).strip().strip('"').strip()
        if teacher and teacher not in ['. .', '']:
            return teacher
    return ""

async def js_click_by_text(page, text):
    try:
        result = await page.evaluate("""
            (target) => {
                const elements = Array.from(document.querySelectorAll('a'));
                const match = elements.find(el => el.textContent.trim().toLowerCase() === target.toLowerCase() && el.offsetParent !== null);
                if (match) { match.click(); return true; }
                const anyMatch = elements.find(el => el.textContent.trim().toLowerCase() === target.toLowerCase());
                if (anyMatch) { anyMatch.click(); return true; }
                return false;
            }
        """, text)
        if result:
            print(f"✅ Клик: {text}")
        else:
            print(f"️ Не найден: {text}")
        return result
    except Exception as e:
        print(f"❌ Ошибка клика: {e}")
        return False

async def wait_for_visible_elements(page, selector, timeout=10000):
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

def parse_month_html(html, month_ui, year):
    soup = BeautifulSoup(html, 'html.parser')
    table = soup.find('table')
    if not table:
        print(f"⚠️ Таблица не найдена для месяца {month_ui}")
        return []
    
    schedule_cells = table.find_all('td', attrs={'data-group': True})
    print(f"🔍 {month_ui}: найдено ячеек: {len(schedule_cells)}")
    
    events_by_date = defaultdict(list)
    
    for cell in schedule_cells:
        try:
            data_day = cell.get('data-day', '')
            data_time = cell.get('data-time', '')
            
            subject_div = cell.find('div', class_='subject')
            aud_div = cell.find('div', class_='aud')
            subject_full = subject_div.get_text(strip=True) if subject_div else ""
            
            # Извлекаем аудиторию
            room = ""
            if aud_div:
                b_tag = aud_div.find('b')
                room = b_tag.get_text(strip=True) if b_tag else aud_div.get_text(strip=True)
            
            # ✅ НОВЫЙ СПОСОБ: извлекаем преподавателя через regex
            teacher = extract_teacher_from_cell(cell)
            
            if not subject_full or subject_full in [". .", ""]:
                continue
            
            # Парсим время
            time_parts = data_time.replace(' ', '').split('-') if data_time else []
            if len(time_parts) != 2:
                time_match = re.search(r'(\d{2}:\d{2})\s*-\s*(\d{2}:\d{2})', cell.get_text(strip=True))
                if time_match:
                    time_parts = [time_match.group(1), time_match.group(2)]
                else:
                    continue
            
            day = int(data_day) if data_day.isdigit() else 1
            month_map = {
                'сентября': '09', 'октября': '10', 'ноября': '11', 'декабря': '12',
                'января': '01', 'февраля': '02', 'марта': '03', 'апреля': '04', 'мая': '05', 'июня': '06',
                'сентябрь': '09', 'октябрь': '10', 'ноябрь': '11', 'декабрь': '12',
                'январь': '01', 'февраль': '02', 'март': '03', 'апрель': '04', 'май': '05', 'июнь': '06'
            }
            month_num = month_map.get(month_ui.lower(), '09')
            date_fmt = f"{day:02d}.{month_num}.{year}"
            
            subject_name, subject_type = parse_subject_name(subject_full)
            
            events_by_date[date_fmt].append({
                "time_start": time_parts[0],
                "time_end": time_parts[1],
                "subject_name": subject_name,
                "subject_type": subject_type,
                "room": room,
                "teacher": teacher,
                "month_ui": month_ui
            })
        except Exception as e:
            print(f"⚠️ Ошибка парсинга ячейки: {e}")
            continue
    
    final_events = []
    for date_fmt, day_events in events_by_date.items():
        day_events.sort(key=lambda x: x['time_start'])
        for slot_number, event in enumerate(day_events, start=1):
            title = f"{slot_number}. {event['subject_type']} {event['subject_name']}" if event['subject_type'] else f"{slot_number}. {event['subject_name']}"
            final_events.append({
                "date": date_fmt,
                "time_start": event['time_start'],
                "time_end": event['time_end'],
                "title": title,
                "subject_name": event['subject_name'],
                "room": event['room'],
                "teacher": event['teacher'],
                "month_ui": event['month_ui']
            })
    
    return final_events

def get_diff(old_list, new_list):
    old_dict = {(e['date'], e['time_start']): e for e in old_list}
    new_dict = {(e['date'], e['time_start']): e for e in new_list}
    
    added, removed, changed = [], [], []
    
    for key, new_e in new_dict.items():
        if key not in old_dict:
            added.append(new_e)
        else:
            old_e = old_dict[key]
            diffs = []
            if old_e.get('subject_name') != new_e.get('subject_name'):
                diffs.append(f"Предмет: {old_e.get('subject_name')} ➡️ {new_e.get('subject_name')}")
            if old_e.get('room') != new_e.get('room'):
                diffs.append(f"Аудитория: {old_e.get('room')} ➡️ {new_e.get('room')}")
            if old_e.get('teacher') != new_e.get('teacher'):
                diffs.append(f"Преподаватель: {old_e.get('teacher')} ➡️ {new_e.get('teacher')}")
            if diffs:
                changed.append((new_e, diffs))
    
    for key, old_e in old_dict.items():
        if key not in new_dict:
            removed.append(old_e)
    
    added.sort(key=lambda x: (x['date'], x['time_start']))
    removed.sort(key=lambda x: (x['date'], x['time_start']))
    changed.sort(key=lambda x: (x[0]['date'], x[0]['time_start']))
    
    return added, removed, changed

def format_telegram_message(added, removed, changed, months_info):
    month_names = ", ".join([m.capitalize() for m, y in months_info[:3]])
    if len(months_info) > 3:
        month_names += f" и ещё {len(months_info) - 3} мес."
    
    msg = f"🚨 <b>Изменения в расписании ({month_names})</b>\n\n"
    
    def group_by_month(events):
        groups = defaultdict(list)
        for ev in events:
            groups[ev.get('month_ui', 'неизвестно')].append(ev)
        return groups
    
    if added:
        msg += "➕ <b>Добавлено:</b>\n"
        for month, events in group_by_month(added).items():
            msg += f"  <i>{month.capitalize()}:</i>\n"
            for ev in events[:5]:
                teacher_info = f" ({ev['teacher']})" if ev.get('teacher') else ""
                msg += f"  • {ev['date']} в {ev['time_start']}: {ev['title']} (ауд. {ev['room']}{teacher_info})\n"
            if len(events) > 5:
                msg += f"  ... и ещё {len(events) - 5} пар\n"
        msg += "\n"
    
    if removed:
        msg += "➖ <b>Отменено:</b>\n"
        for month, events in group_by_month(removed).items():
            msg += f"  <i>{month.capitalize()}:</i>\n"
            for ev in events[:5]:
                msg += f"  • {ev['date']} в {ev['time_start']}: {ev['title']}\n"
            if len(events) > 5:
                msg += f"  ... и ещё {len(events) - 5} пар\n"
        msg += "\n"
    
    if changed:
        msg += "🔄 <b>Изменено:</b>\n"
        for new_e, diffs in changed[:10]:
            msg += f"• {new_e['date']} в {new_e['time_start']} ({new_e.get('month_ui', '')}):\n"
            for d in diffs:
                msg += f"  {d}\n"
        if len(changed) > 10:
            msg += f"... и ещё {len(changed) - 10} изменений\n"
        msg += "\n"
    
    if len(msg) > 4000:
        msg = msg[:3900] + "\n... (слишком много изменений, проверьте сайт вручную)"
    
    return msg

async def main():
    print("🚀 Запуск умного парсера...")
    months_info = get_semester_months()
    month_names = ", ".join([f"{m} {y}" for m, y in months_info])
    print(f"📅 Парсим семестр: {month_names}")
    
    old_events = []
    if os.path.exists('schedule.json'):
        try:
            with open('schedule.json', 'r', encoding='utf-8') as f:
                content = f.read().strip()
                if content:
                    old_events = json.loads(content)
                    print(f"💾 Загружено старое расписание: {len(old_events)} пар")
                else:
                    print("⚠️ Файл schedule.json пустой, считаем первый запуск")
        except (json.JSONDecodeError, Exception) as e:
            print(f"⚠️ Ошибка чтения schedule.json: {e}, считаем первый запуск")
            old_events = []
    else:
        print("🆕 Это первый запуск, старого расписания нет.")
    
    all_events = []
    
    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page()
            await page.goto("https://gtifem.ru/dekanat/raspisanie/", timeout=30000)
            await page.wait_for_load_state("networkidle")
            await page.wait_for_timeout(2000)
            
            await page.evaluate("""
                () => { document.querySelectorAll('.sc-widget, .cookie-banner, .modal, .popup').forEach(el => el.remove()); }
            """)
            print("✅ Баннеры удалены")
            
            print("Выбираем параметры...")
            await js_click_by_text(page, DEPARTMENT); await page.wait_for_timeout(1500)
            await js_click_by_text(page, MAJOR); await wait_for_visible_elements(page, ".section.courses ul li a", timeout=10000); await page.wait_for_timeout(1500)
            await js_click_by_text(page, COURSE); await wait_for_visible_elements(page, ".section.groups ul li a", timeout=10000); await page.wait_for_timeout(1500)
            await js_click_by_text(page, GROUP); await wait_for_visible_elements(page, ".section.months ul li a", timeout=10000); await page.wait_for_timeout(1500)
            
            for month_ui, year in months_info:
                print(f"\n📆 Парсим {month_ui} {year}...")
                await js_click_by_text(page, month_ui)
                await page.wait_for_selector("table", timeout=15000)
                await page.wait_for_timeout(3000)
                
                html = await page.content()
                month_events = parse_month_html(html, month_ui, year)
                print(f"✅ {month_ui}: найдено {len(month_events)} пар")
                all_events.extend(month_events)
                
                await page.wait_for_timeout(1000)
            
            await browser.close()
    
    except Exception as e:
        print(f"❌ Ошибка браузера: {e}")
        return
    
    print(f"\n📚 Всего найдено пар за семестр: {len(all_events)}")
    
    # Считаем сколько пар с преподавателями
    teachers_found = sum(1 for ev in all_events if ev.get('teacher'))
    print(f"‍🏫 Пар с преподавателями: {teachers_found} из {len(all_events)}")
    
    # Создаем календарь с названием
    cal = Calendar()
    cal.add('prodid', '-//GTIFEM Schedule//RU')
    cal.add('version', '2.0')
    cal.add('x-wr-calname', f'ФЭМ - {GROUP}')
    cal.add('x-wr-timezone', 'Europe/Moscow')
    
    tz = pytz.timezone('Europe/Moscow')
    
    for ev in all_events:
        try:
            event = Event()
            event.add('summary', ev['title'])
            event.add('location', ev['room'])
            # Добавляем преподавателя в описание
            description = ev['teacher'] if ev['teacher'] else "Преподаватель не указан"
            event.add('description', description)
            
            start_dt = tz.localize(datetime.strptime(f"{ev['date']} {ev['time_start']}", "%d.%m.%Y %H:%M"))
            end_dt = tz.localize(datetime.strptime(f"{ev['date']} {ev['time_end']}", "%d.%m.%Y %H:%M"))
            
            event.add('dtstart', start_dt)
            event.add('dtend', end_dt)
            cal.add_component(event)
        except Exception as e:
            print(f"️ Ошибка создания события: {e}")
            continue
    
    new_ics_data = cal.to_ical()
    
    added, removed, changed = get_diff(old_events, all_events)
    
    is_full_update = False
    if len(all_events) > 0 and len(added) > len(all_events) * 0.5:
        is_full_update = True
    if len(old_events) > 0 and len(removed) > len(old_events) * 0.5:
        is_full_update = True
    
    # Всегда сохраняем файлы
    with open('schedule.ics', 'wb') as f:
        f.write(new_ics_data)
    with open('schedule.json', 'w', encoding='utf-8') as f:
        json.dump(all_events, f, ensure_ascii=False, indent=2)
    print("💾 Файлы schedule.ics и schedule.json сохранены")
    
    if is_full_update:
        month_names_short = ", ".join([m.capitalize() for m, y in months_info[:3]])
        if len(months_info) > 3:
            month_names_short += f" и др."
        msg = f"🔄 <b>Расписание полностью обновлено ({month_names_short})</b>\n\nГруппа: {GROUP}\nВсего пар в календаре: {len(all_events)}\nПреподавателей указано: {teachers_found}\n\nGoogle Календарь обновится в течение 24 часов."
        send_telegram(msg)
    elif added or removed or changed:
        msg = format_telegram_message(added, removed, changed, months_info)
        send_telegram(msg)
    else:
        print("✅ Изменений не найдено. Уведомление не отправляем.")
        send_telegram("Скрипт отработал. Изменений не найдено.")

if __name__ == "__main__":
    asyncio.run(main())
