# Auto Badges

Утилита подготавливает список регистраций и создаёт PDF-бейджи участников и организаторов. Работает локально. Данные отправляются в ИИ только при ручной загрузке файлов пользователем.

## Установка

Нужен Python 3.10+ и PyMuPDF. В репозитории есть Source Sans 3 Bold под лицензией OFL 1.1; текст лицензии находится в `design/OFL.txt`.

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Положите CSV-экспорт регистраций в `data/input/registrations.csv`. Нужны столбцы `ID`, `First Name`, `Last Name`, `Affiliation`, `Country`; `Name` необязателен. Подготовить таблицу:

```bash
python main.py prepare
```

Для другого файла укажите путь через `--input`. Подготовка не перезаписывает существующую таблицу без `--force`.

## Ручная обработка

Откройте `data/work/participants.csv` в табличном редакторе. Проверьте имена, `Institution` и `Type`; для организаторов укажите `ORGANIZER`, для остальных `PARTICIPANT`. Не меняйте `ID`, `Full Name` и исходную `Affiliation`. После проверки установите `Review=OK`.

Словарь сокращений находится в `data/dictionaries/affiliations.csv`. Неизвестные варианты собраны в `data/work/affiliations_review.csv`. Для индивидуальной правки измените `Institution` участника напрямую. Пустое `Institution` не печатается, если запись отмечена `NEED REVIEW` с причиной `NO_AFFILIATION`.

## Обработка аффилиаций с помощью ИИ

```bash
python main.py export-ai
```

Загрузите в ИИ три файла: `data/ai-patches/INSTRUCTIONS.md`, `data/ai-patches/affiliations_reference.csv` и один JSON из `data/ai-patches/original/`. Обрабатывайте пакеты по одному. Сохраните каждый возвращённый JSON с тем же именем в `data/ai-patches/returned/`.

Затем выполните:

```bash
python main.py import-ai
```

Проверьте `Suggested`, `Sources` и `Notes` в `data/work/affiliations_review.csv`. Для принятых сокращений укажите `Approved=YES`. Если сокращение оставлено пустым и аффилиацию не нужно печатать, также укажите `YES`. Примените решения и создайте PDF:

```bash
python main.py apply
python main.py badges
```

ИИ получает только названия организаций, без имён и ID. Предложения не применяются без ручного одобрения. `apply` снимает только пометку о неизвестной аффилиации и сохраняет остальные причины `NEED REVIEW`. Вместо ИИ можно заполнить `Suggested` и `Approved` вручную.

## PDF и проверка

`python main.py badges` создаёт:

- `output/badges_participants_a4.pdf`
- `output/badges_organizers_a4.pdf`

Фоновые PNG для реальной печати хранятся локально в `design/` и не входят в репозиторий. Пути к PNG и Source Sans 3, а также размеры листа, бейджа и текстовых полей задаются в блоке `CONFIG` файла `main.py`. `settings.py` содержит dataclass-типы настроек; пользовательские параметры макета находятся в `main.py`. Перед печатью проверьте строки `NEED REVIEW` в `data/work/participants.csv`.

Запустить тесты:

```bash
python -m unittest discover -s tests -v
```

В Git не добавляются исходные регистрации, рабочие таблицы, патчи ИИ, PDF и локальные файлы дизайна.
