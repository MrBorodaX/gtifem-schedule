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

# Порядок месяцев на сайте (учебный год)
MONTHS_ORDER = [
    "сентябрь", "октябрь", "ноябрь", "декабрь",
    "январь", "февраль", "март", "апрель", "май", "июнь"
]

def send_telegram(message):
    print(f"📤 Отправка в Telegram...")
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("⚠️ Токены Telegram не найдены!")
        return False
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    data = {"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "HTML"}
    try:
        response = requests.post(url, data=data, timeout=10)
        if response.status_code == 200:
            print("✅ Уведомление отправлено")
            return True
        else:
            print(f"❌ Ошибка API: {response.status_code} - {response.text}")
            return False
    except Exception as e:
        print(f"❌ Ошибка сети: {e}")
        return False

def get_two_months():
    """Возвращает список из двух месяцев: текущий и следующий"""
    now = datetime.now()
    month_num = now.month
    
    # Определяем текущий месяц в учебном году
    # Осенний семестр: сентябрь(9)-декабрь(12), весенний: январь(1)-июнь(6)
    if 9 <= month_num <= 12:
        current_idx = month_num - 9  # сентябрь=0, октябрь=1, ...
    elif 1 <= month_num <= 6:
        current_idx = month_num + 3  # январь=4, февраль=5, ...
    else:
        current_idx = 0  # июль/август — начинаем с сентября
    
    current_month = MONTHS_ORDER[current_idx]
    current_year = now.year if month_num >= 9 else now.year + 1
    
    # Следующий месяц
    next_idx = current_idx + 1
    if next_idx >= len(MONTHS_ORDER):
        next_idx = 0  # переход на новый учебный год
    next_month = MONTHS_ORDER[next_idx]
    next_year = current_year + 1 if next_idx == 0 else current_year
    
    return [(current_month, current_year), (next_month, next_year)]

def parse_subject_name(subject_full):
    match = re.search(r'\((лек|пр|лаб)\)', subject_full, re.IGNORECASE)
    if match:
        return subject_full[:match.start()].strip(), match.group(1).upper()
    return subject_full, ""

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
            print(f"⚠️ Не найден: {text}")
        return result
    except Exception as e:
        print(f" Ошибка клика: {e}")
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
    """Парсит HTML одного месяца и возвращает список событий"""
    soup = BeautifulSoup(html, 'html.parser')
    table = soup.find('table')
    if not table:
        print(f"⚠️ Таблица не найдена для месяца {month_ui}")
        return []
    
    schedule_cells = table.find_all('td', attrs={'data-group': True})
    print(f" {month_ui}: найдено ячеек: {len(schedule_cells)}")
    
    events_by_date = defaultdict(list)
    
    for cell in schedule_cells:
        try:
            data_day = cell.get('data-day', '')
            data_time = cell.get('data-time', '')
            
            subject_div = cell.find('div', class_='subject')
            aud_div = cell.find('div', class_='aud')
            subject_full = subject_div.get_text(strip=True) if subject_div else ""
            
            room = aud_div.find('b').get_text(strip=True) if aud_div and aud_div.find('b') else ""
            teacher = ""
            if aud_div:
                next_div = aud_div.find_next_sibling('div')
                if next_div and (not next_div.get('class') or 'number' not in next_div.get('class', [])):
                    teacher = next_div.get_text(strip=True)
            
            if not subject_full or subject_full in [". .", ""]:
                continue
            
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
            # Определяем номер месяца для даты
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
        except Exception:
            continue
    
    # Сортировка и нумерация по дням
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
    """Сравнивает старое и новое расписание"""
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
    """Формирует сообщение об изменениях с группировкой по месяцам"""
    month_names = " и ".join([m.capitalize() for m, y in months_info])
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
            for ev in events:
                msg += f"  • {ev['date']} в {ev['time_start']}: {ev['title']} (ауд. {ev['room']})\n"
        msg += "\n"
    
    if removed:
        msg += "➖ <b>Отменено:</b>\n"
        for month, events in group_by_month(removed).items():
            msg += f"  <i>{month.capitalize()}:</i>\n"
            for ev in events:
                msg += f"  • {ev['date']} в {ev['time_start']}: {ev['title']}\n"
        msg += "\n"
    
    if changed:
        msg += "🔄 <b>Изменено:</b>\n"
        for new_e, diffs in changed:
            msg += f"• {new_e['date']} в {new_e['time_start']} ({new_e.get('month_ui', '')}):\n"
            for d in diffs:
                msg += f"  {d}\n"
        msg += "\n"
    
    if len(msg) > 4000:
        msg = msg[:3900] + "\n... (слишком много изменений, проверьте сайт вручную)"
    
    return msg

async def main():
    print(" Запуск умного парсера...")
    months_info = get_two_months()
    print(f"📅 Парсим месяцы: {months_info[0][0]} {months_info[0][1]} и {months_info[1][0]} {months_info[1][1]}")
    
    old_events = []
    if os.path.exists('schedule.json'):
        with open('schedule.json', 'r', encoding='utf-8') as f:
            old_events = json.load(f)
        print(f"💾 Загружено старое расписание: {len(old_events)} пар")
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
            
            # Выбираем отделение, направление, курс, группу ОДИН раз
            print("Выбираем параметры...")
            await js_click_by_text(page, DEPARTMENT); await page.wait_for_timeout(1500)
            await js_click_by_text(page, MAJOR); await wait_for_visible_elements(page, ".section.courses ul li a", timeout=10000); await page.wait_for_timeout(1500)
            await js_click_by_text(page, COURSE); await wait_for_visible_elements(page, ".section.groups ul li a", timeout=10000); await page.wait_for_timeout(1500)
            await js_click_by_text(page, GROUP); await wait_for_visible_elements(page, ".section.months ul li a", timeout=10000); await page.wait_for_timeout(1500)
            
            # Парсим каждый месяц по очереди
            for month_ui, year in months_info:
                print(f"\n📆 Парсим {month_ui} {year}...")
                await js_click_by_text(page, month_ui)
                await page.wait_for_selector("table", timeout=15000)
                await page.wait_for_timeout(3000)
                
                html = await page.content()
                month_events = parse_month_html(html, month_ui, year)
                print(f"✅ {month_ui}: найдено {len(month_events)} пар")
                all_events.extend(month_events)
                
                # Небольшая пауза перед следующим месяцем
                await page.wait_for_timeout(1000)
            
            await browser.close()
    
    except Exception as e:
        print(f"❌ Ошибка браузера: {e}")
        return
    
    print(f"\n📚 Всего найдено пар за 2 месяца: {len(all_events)}")
    
    # Создаём ICS
    cal = Calendar()
    cal.add('prodid', '-//GTIFEM Schedule//RU')
    cal.add('version', '2.0')
    tz = pytz.timezone('Europe/Moscow')
    
    for ev in all_events:
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
        except Exception:
            continue
    
    new_ics_data = cal.to_ical()
    
    # Сравниваем со старым расписанием
    added, removed, changed = get_diff(old_events, all_events)
    
    if not added and not removed and not changed:
        print("✅ Изменений не найдено.")
        if not old_events:
            month_names = " и ".join([m.capitalize() for m, y in months_info])
            send_telegram(f"✅ <b>Парсер успешно запущен!</b>\n\nГруппа: {GROUP}\nМесяцы: {month_names}\nПар загружено: {len(all_events)}\n\nТеперь бот будет следить за изменениями.")
    else:
        print("🔥 Найдены изменения! Сохраняем и отправляем...")
        with open('schedule.ics', 'wb') as f:
            f.write(new_ics_data)
        with open('schedule.json', 'w', encoding='utf-8') as f:
            json.dump(all_events, f, ensure_ascii=False, indent=2)
        
        msg = format_telegram_message(added, removed, changed, months_info)
        send_telegram(msg)

if __name__ == "__main__":
    asyncio.run(main())
