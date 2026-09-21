# Copy Tracker

Локальный исследовательский трекер кошельков Solana для отбора кандидатов на копитрейдинг. Python 3.11+, стандартная библиотека, SQLite, GMGN API и Telegram. Торговые операции не выполняет.

## Возможности

- Поиск трейдеров популярных токенов и покупателей свежих запусков Pump.fun.
- Очередь с приоритетами, повторными проверками и адаптивной частотой поиска.
- Проверка реализованного PnL за 30 и 7 дней, удержания и риск-меток.
- Подтверждение нескольких прибыльных токенов через наблюдения и ограниченную историю закрытых позиций.
- Ручное аналитическое досье и отправка вердикта в Telegram после проверки.
- Общий интервал запросов GMGN не менее 6 секунд, обработка 429 и сетевых ошибок.

## Установка и запуск

```powershell
git clone https://github.com/EnergyBeam/copy-tracker.git
cd copy-tracker
Copy-Item .env.example .env
python tracker.py init
python monitor.py
```

Впишите ключ GMGN и настройки Telegram в локальный `.env`. Не публикуйте этот файл. Для настройки чата отправьте боту `/start`, затем запустите `python telegram_setup.py --help` и следуйте доступным командам. Данные создаются рядом со скриптами; папка должна быть доступна для записи.

`seeds.json` содержит исходные исследовательские примеры адресов, не рекомендации. Живой поиск не зависит от этого списка.

## Фоновая работа в Windows

```powershell
.\install_monitor.ps1 -PythonPath "C:\Python311\pythonw.exe"
```

Путь укажите для своей установки Python. Скрипт создаёт задачу `CopyTracker-GMGN` для текущего пользователя. Компьютер должен быть включён, пользовательская сессия активна. Для остановки создайте файл `monitor.stop`; перед повторным запуском удалите его. Для отключения автозапуска используйте `Disable-ScheduledTask -TaskName CopyTracker-GMGN`.

## Ручной анализ

```powershell
python manual_review.py
python manual_review.py --result-file review.json
```

Первый вызов выводит досье и `evidence_hash`. Второй принимает JSON с полями `wallet`, `evidence_hash`, `analysis`. В `analysis`: `verdict` (`reject`, `watch`, `paper_only`), текст `summary`, списки `strengths`, `risks`, `missing_checks`. Устаревший разбор не принимается. После сохранения отчёт отправляется в настроенный Telegram-чат. Фоновый процесс сам не запускает ручной анализ. Экспериментальный OpenAI API-модуль монитором не вызывается.

## Ограничения

Охват токенов выборочный. История ограничена тремя страницами API; пагинация и отсутствие начальных остатков могут ограничивать восстановление позиций. Отсутствие данных не означает убыточность. Нет полной проверки связей адресов, безопасности токенов, исполнимых котировок подписчика или автоматической торговли. Прибыль владельца не гарантирует результат копирования. Досье требуют проверки свежести.

## Проверка

```powershell
python -m unittest discover
```

Основные модули: `monitor.py` — фоновый цикл; `gmgn_review.py` — очередь профилей; `history_metrics.py` — закрытые позиции; `manual_review.py` — ручной разбор; `telegram_notify.py` — доставка. Правила распределения запросов описаны в `queue-policy.md`.

Базы, ключи, снимки API, журналы и личные отчёты исключены из Git.

## Persistent history
Activity pages are cached per wallet in SQLite with deduplication. Each fetch reads the latest page and continues older history from the saved cursor, up to three requests. Pending dossiers are refreshed one per monitor cycle when older than six hours. Provider stats timestamps remain unchanged. Pagination exhaustion does not prove full on-chain history; polling may miss activity between snapshots. GMGN returned 20 events per page in the live verification despite limit=100.

## Coherent manual-review snapshots
Pending dossiers refresh 7D stats, 30D stats and cached activity together, then reapply eligibility. Failed refreshes do not replace the previous dossier. Legacy snapshots and snapshots older than six hours require refresh; manual submission rejects them. Use `python manual_review.py --refresh-wallet ADDRESS` before reviewing stale entries. The monitor refreshes one stale pending dossier per cycle under the shared API pacer. The history cache may remain incomplete.
