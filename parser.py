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

async def select_bitrix_dropdown(page, section_class, value_text):
    """Специальный метод для кастомных дропдаунов Bitrix"""
    try:
        # 1. Находим секцию дропдауна
        section = page.locator(f".section.{section_class}").first
        
        # 2. Кликаем по заголовку, чтобы раскрыть список
        await section.locator(".title").first.click()
        await page.wait_for_timeout(400)
        
        # 3. Ищем ссылку с нужным текстом внутри ul li и кликаем по ней
        await section.locator(f"ul li a:has-text('{value_text}')").first.click()
        await page.wait_for_timeout(800)
        print(f"✅ Выбрано: {value_text}")
    except Exception as e:
        print(f"⚠️ Ошибка выбора {section_class} '{value_text}': {e}")
        # Fallback: пробуем обычный JS клик, если структура изменилась
        try:
            await page.evaluate(f"""
                () => {{
                    const el = Array.from(document.querySelectorAll('a, li, div')).find(e => e.textContent.trim() === '{value_text}');
                    if (el) {{ el.scrollIntoView(); el.click(); }}
                }}
            """)
            await page.wait_for_timeout(800)
            print(f"✅ Выбрано (fallback): {value_text}")
        except:
            pass

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
            
            # Переходим на сайт
            await page.goto("https://gtifem.ru/dekanat/raspisanie/", timeout=30000)
            await page.wait_for_load_state("networkidle")
            await page.wait_for_timeout(2000)
            
            # 1. Закрываем баннер cookie, если он есть
            try:
                await page.get_by_role("button", name="Принять").click(timeout=3000)
                print("✅ Баннер cookie закрыт")
                await page.wait_for_timeout(1000)
            except:
                print("ℹ️ Баннер cookie не найден или уже закрыт")
            
            # 2. Последовательно выбираем параметры через специфичные для Bitrix селекторы
            # Отделение и Направление часто не имеют явных class="section", поэтому для них используем fallback или общие селекторы
            print("Выбираем параметры...")
            
            # Попробуем найти секции по порядку
            sections = await page.locator(".section").all()
            print(f"Найдено секций .section: {len(sections)}")
            
            # Если секции есть, используем их. Если нет, используем универсальный метод
            if len(sections) >= 2:
                # Предполагаем, что порядок: 0-отделение, 1-направление, 2-курс, 3-группа, 4-месяц
                # Но лучше искать по содержимому заголовка
                targets = [
                    ("groups", GROUP),
                    ("months", current_month)
                ]
                for sec_class, val in targets:
                    await select_bitrix_dropdown(page, sec_class, val)
                
                # Для отделения, направления и курса попробуем универсальный клик, если они не в .section
                for text in [DEPARTMENT, MAJOR, COURSE]:
                    try:
                        await page.evaluate(f"""
                            () => {{
                                const el = Array.from(document.querySelectorAll('a, li, div')).find(e => e.textContent.trim() === '{text}');
                                if (el) {{ el.scrollIntoView({{block: 'center'}}); el.click(); }}
                            }}
                        """)
                        await page.wait_for_timeout(600)
                        print(f"✅ Выбрано: {text}")
                    except:
                        pass
            else:
                # Если секций нет, используем только универсальный метод для всех
                for text in [DEPARTMENT, MAJOR, COURSE, GROUP, current_month]:
                    try:
                        await page.evaluate(f"""
                            () => {{
                                const el = Array.from(document.querySelectorAll('a, li, div')).find(e => e.textContent.trim() === '{text}');
                                if (el) {{ el.scrollIntoView({{block: 'center'}}); el.click(); }}
                            }}
                        """)
                        await page.wait_for_timeout(800)
                        print(f"✅ Выбрано: {text}")
                    except:
                        pass

            print("⏳ Ожидаем загрузки таблицы расписания...")
            # Ждем появления таблицы в DOM (state='attached' означает, что элемент добавлен в DOM, даже если скрыт)
            try:
                await page.wait_for_selector("table", state="attached", timeout=15000)
                print("✅ Таблица найдена в DOM!")
            except:
                print("⚠️ Таблица <table> не появилась за 15 секунд.")
            
            # Даем дополнительное время на отрисовку и AJAX
            await page.wait_for_timeout(3000)
            
            html = await page.content()
            await browser.close()
            
    except Exception as e:
        print(f"❌ Критическая ошибка браузера: {e}")
        with open('schedule.ics', 'wb') as f:
            f.write(b"BEGIN:VCALENDAR\nVERSION:2.0\nPRODID:-//GTIFEM//RU\nEND:VCALENDAR")
        return

    # Проверяем, загрузилось ли расписание
    if GROUP not in html and "Основы российской государственности" not in html:
        print("❌ Расписание не загрузилось. Группа или предметы не найдены в HTML.")
        # Сохраняем скриншот и HTML для отладки прямо в репозиторий
        with open('debug.html', 'w', encoding='utf-8') as f:
            f.write(html)
        print("💾 Файл debug.html сохранен в репозитории для анализа.")
        with open('schedule.ics', 'wb') as f:
            f.write(b"BEGIN:VCALENDAR\nVERSION:2.0\nPRODID:-//GTIFEM//RU\nEND:VCALENDAR")
        return

    print("✅ Данные расписания найдены в HTML!")
    soup = BeautifulSoup(html, 'html.parser')
    
    # Ищем ячейки с data-group или просто все ячейки в таблице
    table = soup.find('table')
    if table:
        schedule_cells = table.find_all('td', attrs={'data-group': True})
        if not schedule_cells:
            schedule_cells = table.find_all('td')
    else:
        schedule_cells = soup.find_all('div', class_=lambda c: c and ('schedule' in c.lower() or 'group' in c.lower()))

    print(f"🔍 Найдено потенциальных ячеек расписания: {len(schedule_cells)}")
    
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
            
            import re
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
            print(f"⚠️ Ошибка создания события: {e}")
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
