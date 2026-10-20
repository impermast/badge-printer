# badge-printer

Локальная подготовка данных Indico и печать бейджей 2 × 2 на А4. Без доступа к серверу Indico, внешних API и обязательного использования ИИ.

## Быстрый старт

Нужен Python 3.10+ и системный жирный шрифт DejaVu Sans или Liberation Sans.

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Для проверки без реальных данных:

```bash
python main.py prepare --input data/examples/registrations_demo.csv
python main.py badges
```

Результаты: `data/work/participants.csv`, `data/work/review.html` и `output/badges_a4.pdf`.

## Реальная конференция

1. Положите экспорт Indico в `data/input/registrations.csv`. Нужны поля `ID`, `First Name`, `Last Name`, `Affiliation`, `Country`, желательно `Name`.
2. Запустите `python main.py prepare` **один раз**.
3. Откройте `data/work/participants.csv` в LibreOffice (кодировка UTF-8, разделитель запятая). Исправьте ФИО и `Institution`, где нужно. Исходные `Full Name` и `Affiliation` сохраняйте.
4. В `data/work/review.html` строки `NEED REVIEW` подсвечены жёлтым. После ручной проверки в CSV можно поставить `Review=OK`.
5. Для бейджа организатора поменяйте поле `Type` на `ORGANIZER`.
6. Запустите `python main.py badges` **без `--input`**. Команда печатает только из `data/work/participants.csv`, а не из экспорта Indico. Раскладка 4 бейджа на А4, размер бейджа 105 × 148 мм, без меток реза.

Если нужно указать свой исходный экспорт, это делается на этапе подготовки:

```bash
python main.py prepare --input data/input/registrations_cutted.csv
python main.py badges
```

Не используйте `prepare --force` для обновления бейджей: это уничтожает ручные правки в рабочей таблице.

Повторно запускать `prepare` **не нужно**: печать берёт данные непосредственно из исправленного CSV. `prepare --force` намеренно стирает эту работу.

### Словарь сокращений

`data/dictionaries/affiliations.csv` содержит утверждённые пары `Affiliation,Institution`. Применяется точное сопоставление без учёта регистра и лишних пробелов. Для двойных и тройных аффилиаций скрипт объединяет сокращения через ` / `, **только если распознал каждую составляющую**. Неизвестные варианты попадают в `data/work/affiliations_review.csv`, каждая уникальная исходная строка один раз, со счётчиком повторений.

### Исследование неизвестных аффилиаций через ChatGPT

```bash
python main.py export-ai
```

Появятся `data/patches/INSTRUCTIONS.md` и JSON-пакеты `data/patches/original/batch_001.json` и т.д. Размер пакета настраивается через `Processing(batch_size=100)` в `main.py`.

1. Загрузите в ChatGPT три файла: `data/patches/INSTRUCTIONS.md`, `data/patches/affiliations_reference.csv` и **один** пакет из `data/patches/original/`, например `batch_001.json`. Справочник нужен для использования уже принятых сокращений.
2. Попросите вернуть исправленный JSON в прежнем формате и с тем же именем. Сохраните его в `data/patches/returned/batch_001.json`; повторите для остальных пакетов.
3. Запустите `python main.py import-ai`. Программа проверит идентичность исходных названий и полноту пакетов. Если хотя бы один пакет неверен, таблица не изменится. **Важно:** `import-ai` только переносит предложения в таблицу аффилиаций, а не обновляет бейджи.
4. Откройте `data/work/affiliations_review.csv` в LibreOffice / Excel и проверьте `Suggested`, `Sources`, `Notes`. Если ChatGPT оставил `Suggested` пустым, **впишите проверенное сокращение вручную в эту ячейку**. Для каждого утверждённого сокращения укажите `Approved=YES` (именно английскими буквами). Сохраните файл как CSV UTF-8.
5. Запустите `python main.py apply`. Одобренные сокращения попадут в словарь и во все подходящие строки участников. Индивидуально отредактированные `Institution` не перезаписываются. **Успешный `import-ai` без `apply` не меняет `Institution`.**
6. Повторно проверьте `Review` и запустите `python main.py badges`.

ИИ получает **только уникальные названия организаций**, без имён, email или ID участников. Для имён предусмотрена автоматическая транслитерация, а предпочтительное английское написание правится прямо в `participants.csv`.

Можно обойтись вообще без ChatGPT: после `prepare` вручную заполните `Suggested` и `Approved=YES` в `data/work/affiliations_review.csv`, затем выполните `python main.py apply`.

Чтобы исправить **только одного человека**, откройте `data/work/participants.csv`, отредактируйте `Institution`, а затем поставьте `Review=OK` после проверки. Исходное `Affiliation` не изменяйте.

`data/patches` содержит данные одного сеанса обмена; для нового сеанса после успешного импорта перенесите старое содержимое в резервную папку и повторите `export-ai`. Не меняйте `affiliations_review.csv` между `export-ai` и `import-ai`: защита целостности отклонит импорт. Редактировать `Suggested` и `Approved` следует после импорта.

## Настройки

- `main.py`, верхний блок `CONFIG`: пути к данным и фонам, формат листа, размер бейджа, позиции и размеры шрифтов, строгость печати.
- `settings.py`: определения dataclass `Paths`, `Sheet`, `Badge`, `TextField`, `Typography`, `Processing`. Обычно их менять не нужно.
- `design/*.png` или одностраничные PDF: фоны (логотипы, QR, дата, слово PARTICIPANT/ORGANIZER уже встроены). Для PDF поменяйте соответствующий путь в `main.py`.
- `Settings(strict_review=True)`: запрет печати при наличии `NEED REVIEW`. По умолчанию `False` для тестирования.

`generate.py` никогда не обрезает или не делит фамилию и имя. Шрифт уменьшается в заданных пределах. Аффилиацию можно разделить на две строки **между словами или организациями**. Если **аффилиация** всё равно не помещается, программа добавит `AFFILIATION_TOO_LONG` в `Notes`, выставит `NEED REVIEW` и продолжит генерацию остальных бейджей. На проблемном черновом бейдже **Institution останется пустым**. Исправьте сокращение и повторите `badges`, метка переполнения исчезнет. Другие причины проверки сохраняются.

Имена/фамилии обрабатываются строго: если не помещается фамилия, генератор по-прежнему останавливается, чтобы не изготовить бейдж с повреждённым ФИО. Перед печатью проверьте число строк `NEED REVIEW`.

Команда `python main.py review` обновляет HTML-предпросмотр и повторно проверяет длину аффилиаций.

## Проверка и Git

```bash
python -m unittest discover -s tests -v

git init
git add .
git commit -m "Initial badge printer"
```

`.gitignore` исключает реальные регистрации, обработанные персональные данные, патчи ИИ и PDF. В Git попадают код, примеры, шаблоны и утверждённый словарь. **Перед публикацией репозитория отдельно проверьте право размещать фирменные шаблоны конференции и QR-коды.**
