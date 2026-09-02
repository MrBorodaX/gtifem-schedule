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

STATE_FILE = 'schedule_state.json'
ICS_FILE = 'schedule.ics'
DEBUG_FILE = 'debug.html'

def send_telegram(message):
    """Отправка уведомления в Telegram с разбивкой на части, если сообщение длинное"""
    print(f"📤 Попытка отправить в Telegram: {TELEGRAM_BOT_TOKEN[:10] if TELEGRAM_BOT_TOKEN else 'None'}... / {TELEGRAM_CHAT_ID}")
    if not TELEGRAM_BOT_TOKEN or not TELELEGRAM_CHAT_ID:
        print("⚠️ Telegram токены не настроены!")
        return False
    
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    
    # Telegram ограничивает сообщение 4096 символами, разбиваем если нужно
    chunks = []
    if len(message) <= 4000:
        chunks = [message]
    else:
        # Разбиваем по строкам, не разрывая их
        lines = message.split('\n')
        current_chunk = ""
        for line in lines:
            if len(current_chunk) + len(line) + 1 > 4000:
                chunks.append(current_chunk)
                current_chunk = line
            else:
                current_chunk = (current_chunk + '\n' + line).strip()
        if current_chunk:
            chunks.append(current_chunk)
    
    success = True
    for i, chunk in enumerate(chunks, 1):
        try:
            response = requests.post(url, data={"chat_id": TELEGRAM_CHAT_ID, "text": chunk, "parse_mode": "HTML"}, timeout=10)
            if response.status_code == 200:
                print(f"✅ Часть {i}/{len(chunks)} отправлена успешно")
            else:
                print(f"❌ Ошибка Telegram API (часть {i}): {response.status_code} - {response.text}")
                success = False
        except Exception as e:
            print(f"❌ Ошибка отправки (часть {i}): {e}")
            success = False
    return success

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

def load_previous_state():
    """Загружает предыдущее состояние расписания"""
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            print(f"⚠️ Ошибка чтения {STATE_FILE}: {e}")
    return None

def save_state(events_data):
    """Сохраняет текущее состояние расписания"""
    with open(STATE_FILE, 'w', encoding='utf-8') as f:
        json.dump(events_data, f, ensure_ascii=False, indent=2)

def parse_subject_name(subject_full):
    """Парсит название предмета и тип занятия"""
    match = re.search(r'\((лек|пр|лаб)\)', subject_full, re.IGNORECASE)
    if match:
        subject_type = match.group(1).upper()
        subject_name = subject_full[:match.start()].strip()
        return subject_name, subject_type
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
        print(f"❌ Ошибка клика '{text}': {e}")
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

def build_event_key(event):
    """Уникальный ключ события для сравнения (без номера пары)"""
    return (event['date'], event['time_start'], event['subject_name'], event['subject_type'])

def compare_schedules(old_state, new_events):
    """Сравнивает старое и новое расписание, возвращает отчет об изменениях"""
    if old_state is None:
        return None, "first_run"
    
    # Индексируем по ключу
    old_dict = {}
    for ev in old_state:
        key = build_event_key(ev)
        old_dict[key] = ev
    
    new_dict = {}
    for ev in new_events:
        key = build_event_key(ev)
        new_dict[key] = ev
    
    old_keys = set(old_dict.keys())
    new_keys = set(new_dict.keys())
    
    added_keys = new_keys - old_keys
    removed_keys = old_keys - new_keys
    common_keys = old_keys & new_keys
    
    # Проверяем изменения в общих событиях (аудитория, преподаватель)
    changed = []
    for key in common_keys:
        old_ev = old_dict[key]
        new_ev = new_dict[key]
        changes = []
        if old_ev['room'] != new_ev['room']:
            changes.append(('room', old_ev['room'], new_ev['room']))
        if old_ev['teacher'] != new_ev['teacher']:
            changes.append(('teacher', old_ev['teacher'], new_ev['teacher']))
        if old_ev['time_end'] != new_ev['time_end']:
            changes.append(('time_end', old_ev['time_end'], new_ev['time_end']))
        if changes:
            changed.append((key, changes))
    
    added = [new_dict[k] for k in sorted(added_keys)]
    removed = [old_dict[k] for k in sorted(removed_keys)]
    
    return {
        'added': added,
        'removed': removed,
        'changed': changed
    }, "has_changes" if (added or removed or changed) else "no_changes"

def format_event_short(ev):
    """Короткое форматирование события для отчета"""
    title = f"{ev['slot_number']}. {ev['subject_type']} {ev['subject_name']}" if ev['subject_type'] else f"{ev['slot_number']}. {ev['subject_name']}"
    return f"• {ev['date']}, {title}\n   {ev['room']} | 👤 {ev['teacher']}"

def build_telegram_report(changes, group, month_ui):
    """Формирует HTML-отчет для Telegram"""
    report = f" <b>Изменения в расписании</b>\n\n"
    report += f"👥 Группа: {group}\n"
    report += f" Месяц: {month_ui.capitalize()}\n\n"
    
    has_content = False
    
    if changes['added']:
        has_content = True
        report += " <b>Добавлено:</b>\n"
        for ev in changes['added']:
            report += format_event_short(ev) + "\n\n"
    
    if changes['removed']:
        has_content = True
        report += "➖ <b>Удалено:</b>\n"
        for ev in changes['removed']:
            report += format_event_short(ev) + "\n\n"
    
    if changes['changed']:
        has_content = True
        report += "🔄 <b>Изменено:</b>\n"
        for key, diffs in changes['changed']:
            ev = {
                'date': key[0], 'time_start': key[1],
                'subject_name': key[2], 'subject_type': key[3],
                'slot_number': 0, 'room': '', 'teacher': ''
            }
            # Найдем номер пары из нового состояния
            title = f"{ev['subject_type']} {ev['subject_name']}" if ev['subject_type'] else ev['subject_name']
            report += f"• {ev['date']}, {ev['time_start']} — {title}\n"
            for field, old_val, new_val in diffs:
                field_names = {'room': '📍 Аудитория', 'teacher': '👤 Преподаватель', 'time_end': '⏰ Конец'}
                fname = field_names.get(field, field)
                report += f"  Было: {old_val}\n  Стало: {new_val}\n"
            report += "\n"
    
    if not has_content:
        report += "✅ Изменений не обнаружено."
    
    return report

async def main():
    print("🚀 Запуск умного парсера...")
    
    current_month_ui, current_year = get_current_month_and_year()
    print(f"📅 Парсим месяц: {current_month_ui} {current_year} года")
    
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
        send_telegram(f"❌ <b>Ошибка парсера!</b>\n\nГруппа: {GROUP}\nОшибка: {str(e)[:200]}")
        return

    if GROUP not in html:
        print("❌ Расписание не загрузилось.")
        with open(DEBUG_FILE, 'w', encoding='utf-8') as f:
            f.write(html)
        soup = BeautifulSoup(html, 'html.parser')
        body_text = soup.body.get_text(separator=' ', strip=True) if soup.body else ""
        print(f"🔍 ТЕКСТ:\n{body_text[:1000]}")
        send_telegram(f"❌ <b>Расписание не загрузилось!</b>\n\nГруппа: {GROUP}\nМесяц: {current_month_ui.capitalize()}\n\nПроверьте логи GitHub Actions.")
        return

    print("✅ Данные найдены!")
    soup = BeautifulSoup(html, 'html.parser')
    
    table = soup.find('table')
    if not table:
        print(" Таблица не найдена")
        return
    
    schedule_cells = table.find_all('td', attrs={'data-group': True})
    print(f"🔍 Найдено ячеек: {len(schedule_cells)}")
    
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
    
    # Сортируем по времени и присваиваем номера по порядку в день
    final_events = []
    for date_fmt, day_events in events_by_date.items():
        day_events.sort(key=lambda x: x['time_start'])
        for slot_number, event in enumerate(day_events, start=1):
            event['slot_number'] = slot_number
            event['date'] = date_fmt
            final_events.append(event)
    
    print(f"📚 Найдено пар: {len(final_events)}")
    
    # === СРАВНЕНИЕ СО СТАРЫМ СОСТОЯНИЕМ ===
    old_state = load_previous_state()
    changes, status = compare_schedules(old_state, final_events)
    
    if status == "first_run":
        print("️ Первый запуск — сохраняем расписание без уведомлений об изменениях.")
        save_state(final_events)
        send_telegram(f"✅ <b>Парсер запущен!</b>\n\nГруппа: {GROUP}\nМесяц: {current_month_ui.capitalize()}\nПар загружено: {len(final_events)}\n\nТеперь бот будет следить за изменениями.")
    elif status == "no_changes":
        print("✅ Расписание не изменилось.")
        # Можно раскомментировать, если хотите получать уведомления даже при отсутствии изменений:
        # send_telegram(f"✅ <b>Проверка расписания</b>\n\nГруппа: {GROUP}\nМесяц: {current_month_ui.capitalize()}\nПар: {len(final_events)}\n\nИзменений нет.")
    elif status == "has_changes":
        print("🔥 Обнаружены изменения!")
        save_state(final_events)
        report = build_telegram_report(changes, GROUP, current_month_ui)
        send_telegram(report)
    else:
        print("️ Неизвестный статус.")
    
    # === ГЕНЕРАЦИЯ ICS (всегда, чтобы файл был актуальным) ===
    cal = Calendar()
    cal.add('prodid', '-//GTIFEM Schedule//RU')
    cal.add('version', '2.0')
    tz = pytz.timezone('Europe/Moscow')
    
    for ev in final_events:
        try:
            event = Event()
            title = f"{ev['slot_number']}. {ev['subject_type']} {ev['subject_name']}" if ev['subject_type'] else f"{ev['slot_number']}. {ev['subject_name']}"
            event.add('summary', title)
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

    with open(ICS_FILE, 'wb') as f:
        f.write(cal.to_ical())
    print(f"💾 Файл {ICS_FILE} сохранен.")

if __name__ == "__main__":
    asyncio.run(main())

if __name__ == "__main__":
    asyncio.run(main())
