import asyncio
import os
import requests
import hashlib
from playwright.async_api import async_playwright
from bs4 import BeautifulSoup
from icalendar import Calendar, Event
from datetime import datetime
import pytz

TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
TELEGRAM_CHAT_ID = os.getenv('TELEGRAM_CHAT_ID')

def send_telegram(message):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("Telegram токены не найдены, пропускаем уведомление.")
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    try:
        requests.post(url, data={"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "HTML"})
        print("Уведомление в Telegram отправлено.")
    except Exception as e:
        print(f"Ошибка отправки в Telegram: {e}")

def get_hash(filepath):
    if not os.path.exists(filepath): return None
    with open(filepath, 'rb') as f: return hashlib.md5(f.read()).hexdigest()

async def main():
    print("🚀 Запуск парсера расписания...")
    events_data = []
    
    try:
        async with async_playwright() as p:
            print("Запускаем браузер...")
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page()
            
            print("Переход на сайт...")
            await page.goto("https://gtifem.ru/dekanat/raspisanie/", timeout=30000)
            await page.wait_for_load_state("networkidle")
            
            # Параметры для выбора (замените на реальные, если нужно)
            targets = ["Бакалавриат", "Экономика", "1 курс", "1001", "Сентябрь"]
            for text in targets:
                try:
                    # Ищем элемент по тексту и кликаем
                    await page.get_by_text(text, exact=True).first.click()
                    await page.wait_for_timeout(800) # Ждем реакции сайта
                    print(f"✅ Выбрано: {text}")
                except Exception as e:
                    print(f"⚠️ Не удалось выбрать '{text}': {e}")
            
            print("Ожидаем появления таблицы расписания...")
            try:
                # Ждем любую таблицу на странице
                await page.wait_for_selector("table", timeout=15000)
                print("✅ Таблица найдена!")
            except Exception as e:
                print("❌ Таблица не найдена за 15 секунд. Возможно, сайт изменил структуру или заблокировал запрос.")
            
            html = await page.content()
            await browser.close()
            
    except Exception as e:
        print(f"❌ Критическая ошибка Playwright: {e}")
        send_telegram(f"❌ Ошибка парсера:\n{e}")
        return # Прерываем выполнение, чтобы не создавать пустой ICS

    print("Анализируем HTML...")
    soup = BeautifulSoup(html, 'html.parser')
    
    # Ищем все строки таблицы
    rows = soup.find_all('tr')
    print(f"Найдено строк <tr>: {len(rows)}")
    
    for row in rows:
        cells = row.find_all(['td', 'th'])
        # В расписании обычно минимум 4-5 ячеек: Дата, Время, Предмет, Аудитория, Преподаватель
        if len(cells) >= 4:
            date_str = cells[0].get_text(strip=True)
            time_str = cells[1].get_text(strip=True)
            subject = cells[2].get_text(strip=True)
            
            # Определяем, где аудитория, а где преподаватель (зависит от верстки сайта)
            # Обычно: [Дата, Время, Предмет, Аудитория, Преподаватель] или наоборот
            room = cells[3].get_text(strip=True) if len(cells) > 3 else "Не указано"
            teacher = cells[4].get_text(strip=True) if len(cells) > 4 else "Не указано"
            
            # Фильтруем заголовки и пустые строки
            if not date_str or "Дата" in date_str or subject in [". .", "", "День знаний"]:
                continue
                
            events_data.append({
                "date": date_str, 
                "time": time_str, 
                "subject": subject, 
                "room": room, 
                "teacher": teacher
            })

    print(f"📊 Извлечено пар: {len(events_data)}")

    if not events_data:
        send_telegram("⚠️ Парсер не нашел ни одной пары. Проверьте логи GitHub Actions.")
        return

    # Создаем ICS файл
    cal = Calendar()
    cal.add('prodid', '-//GTIFEM Schedule//RU')
    cal.add('version', '2.0')
    tz = pytz.timezone('Europe/Moscow')
    
    month_map = {
        'сентября': '09', 'октября': '10', 'ноября': '11', 'декабря': '12',
        'января': '01', 'февраля': '02', 'марта': '03', 'апреля': '04', 'мая': '05'
    }
    
    for ev in events_data:
        try:
            event = Event()
            event.add('summary', ev['subject'])
            event.add('location', ev['room'])
            event.add('description', ev['teacher'])
            
            # Парсинг даты (например: "1 сентября" -> "01.09.2026")
            parts = ev['date'].split()
            if len(parts) >= 2:
                day = parts[0].zfill(2)
                month_name = parts[1].lower()
                month = month_map.get(month_name, '09')
                date_fmt = f"{day}.{month}.2026" # Используем 2026 год
                
                # Парсинг времени (например: "09:30 - 11:10")
                time_clean = ev['time'].replace(' ', '').replace('\n', '')
                if '-' in time_clean:
                    t_start, t_end = time_clean.split('-')
                else:
                    continue # Пропускаем, если время не распарсилось
                
                start_dt = tz.localize(datetime.strptime(f"{date_fmt} {t_start}", "%d.%m.%Y %H:%M"))
                end_dt = tz.localize(datetime.strptime(f"{date_fmt} {t_end}", "%d.%m.%Y %H:%M"))
                
                event.add('dtstart', start_dt)
                event.add('dtend', end_dt)
                cal.add_component(event)
        except Exception as e:
            print(f"⚠️ Ошибка парсинга строки {ev}: {e}")
            continue

    # Сохраняем файл
    with open('schedule.ics', 'wb') as f:
        f.write(cal.to_ical())
    print("💾 Файл schedule.ics успешно создан.")
    
    send_telegram(f"✅ Расписание успешно обновлено!\nНайдено и добавлено пар: {len(events_data)}")

if __name__ == "__main__":
    asyncio.run(main())
