import asyncio
import os
import requests
from playwright.async_api import async_playwright
from bs4 import BeautifulSoup
from icalendar import Calendar, Event
from datetime import datetime
import pytz

# === НАСТРОЙКИ (Можно менять прямо здесь или через GitHub Secrets) ===
DEPARTMENT = "Бакалавриат"
MAJOR = "Логистика"       # <-- Проверьте, точно ли так написано на сайте
COURSE = "1 курс"
GROUP = "6661"             # <-- Ваш номер группы
MONTH = "Сентябрь"

TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
TELEGRAM_CHAT_ID = os.getenv('TELEGRAM_CHAT_ID')

def send_telegram(message):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("Telegram токены не найдены.")
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    try:
        requests.post(url, data={"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "HTML"})
    except Exception as e:
        print(f"Ошибка Telegram: {e}")

async def select_option(page, text):
    """Умный выбор элемента из кастомного дропдауна"""
    try:
        # Попытка 1: Стандартный select (если вдруг это он)
        try:
            await page.locator("select").select_option(label=text, timeout=2000)
            print(f"✅ Выбрано (select): {text}")
            return
        except:
            pass
        
        # Попытка 2: Клик с force=True (обходит проверку видимости для кастомных меню)
        await page.get_by_text(text, exact=True).first.click(force=True, timeout=5000)
        await page.wait_for_timeout(800) # Ждем, пока сайт обработает клик и обновит данные
        print(f"✅ Выбрано (force click): {text}")
    except Exception as e:
        print(f"⚠️ Не удалось выбрать '{text}': {e}")

async def main():
    print("🚀 Запуск парсера...")
    events_data = []
    
    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page()
            print("Переход на сайт...")
            await page.goto("https://gtifem.ru/dekanat/raspisanie/", timeout=30000)
            await page.wait_for_load_state("networkidle")
            
            # Последовательно выбираем параметры
            targets = [DEPARTMENT, MAJOR, COURSE, GROUP, MONTH]
            for text in targets:
                await select_option(page, text)
            
            print("Ожидаем появления таблицы расписания...")
            try:
                # Ждем таблицу. Иногда она появляется внутри div с классом .schedule или .table-responsive
                await page.wait_for_selector("table", timeout=15000)
                print("✅ Таблица найдена!")
            except Exception as e:
                print("❌ Таблица не найдена. Возможно, неверно указаны параметры группы/курса.")
                # Делаем скриншот для отладки (сохранится в артефактах GitHub, если настроить, но пока просто в лог)
                print("HTML фрагмент body:", await page.locator("body").inner_html()[:500])
            
            html = await page.content()
            await browser.close()
            
    except Exception as e:
        print(f"❌ Критическая ошибка Playwright: {e}")
        send_telegram(f"❌ Ошибка парсера:\n{e}")
        create_empty_ics()
        return

    print("Анализируем HTML...")
    soup = BeautifulSoup(html, 'html.parser')
    table = soup.find('table')
    
    if not table:
        print("❌ Таблица не найдена в распарсенном HTML")
        create_empty_ics()
        return

    rows = table.find_all('tr')
    print(f"🔍 Найдено строк в таблице: {len(rows)}")
    
    # 1. Парсим заголовки (даты)
    headers = [th.get_text(strip=True) for th in rows[0].find_all(['th', 'td'])]
    
    date_cols = []
    for i, h in enumerate(headers):
        if any(m in h for m in ['сентября', 'октября', 'ноября', 'декабря', 'января', 'февраля', 'марта', 'апреля', 'мая', 'июня']):
            date_cols.append((i, h))
    
    print(f"📅 Найдены колонки с датами: {len(date_cols)} шт.")

    # 2. Парсим матрицу: ищем строку с аудиториями (содержит "а." или ". .")
    for row_idx, row in enumerate(rows):
        cells = row.find_all(['td', 'th'])
        cell_texts = [c.get_text(strip=True) for c in cells]
        
        # Если это строка аудиторий (проверяем со 2-й ячейки)
        if len(cell_texts) > 1 and any("а." in text or text == ". ." for text in cell_texts[1:]):
            if row_idx > 0 and row_idx < len(rows) - 1:
                prev_cells = rows[row_idx - 1].find_all(['td', 'th']) # Строка с предметами
                next_cells = rows[row_idx + 1].find_all(['td', 'th']) # Строка с преподавателями
                
                # Время берем из текущей или предыдущей строки (первая колонка)
                time_text = cells[0].get_text(strip=True)
                if "-" not in time_text and len(prev_cells) > 0:
                    time_text = prev_cells[0].get_text(strip=True)
                
                for col_idx, (date_idx, date_name) in enumerate(date_cols):
                    target_idx = col_idx + 1 # +1, так как 0-я колонка это время
                    
                    if target_idx < len(cells) and target_idx < len(prev_cells) and target_idx < len(next_cells):
                        subject = prev_cells[target_idx].get_text(strip=True)
                        room = cells[target_idx].get_text(strip=True)
                        teacher = next_cells[target_idx].get_text(strip=True)
                        
                        # Игнорируем пустые ячейки или ". ."
                        if subject and subject not in [". .", ""] and room not in [". .", ""]:
                            events_data.append({
                                "date": date_name,
                                "time": time_text,
                                "subject": subject,
                                "room": room,
                                "teacher": teacher
                            })

    print(f"📊 Успешно извлечено пар: {len(events_data)}")
    
    if not events_data:
        print("⚠️ Пары не найдены. Проверьте, правильно ли указаны МАЖОР и ГРУППА в начале скрипта.")
        send_telegram("⚠️ Парсер не нашел пары. Проверьте настройки (Логистика, 6661 и т.д.)")
    else:
        send_telegram(f"✅ Парсер успешно отработал!\nГруппа: {GROUP}\nНайдено пар: {len(events_data)}")

    # 3. Создаем ICS файл
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
                date_fmt = f"{day}.{month}.2026"
                
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
            print(f"⚠️ Ошибка парсинга строки {ev}: {e}")
            continue

    with open('schedule.ics', 'wb') as f:
        f.write(cal.to_ical())
    print("💾 Файл schedule.ics успешно создан.")

def create_empty_ics():
    with open('schedule.ics', 'wb') as f:
        f.write(b"BEGIN:VCALENDAR\nVERSION:2.0\nPRODID:-//GTIFEM//RU\nEND:VCALENDAR")

if __name__ == "__main__":
    asyncio.run(main())

if __name__ == "__main__":
    asyncio.run(main())
