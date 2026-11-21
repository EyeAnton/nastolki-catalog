# Boardex.am — каталог б/у настольных игр (Армения)

Каталог объявлений о продаже и обмене настольных игр из Telegram-канала
[@used_boardgames_armenia](https://t.me/used_boardgames_armenia). Карточка = обложка,
рейтинг и параметры с BoardGameGeek, цена, язык, ссылка на исходное сообщение.
Без монетизации, личная инициатива.

- Сайт: https://nastolki-catalog.pages.dev (Cloudflare Pages)
- API правок продавца: Worker `nastolki-api` (`worker/`)
- Правила работы с данными для Claude — [CLAUDE.md](CLAUDE.md), карта кода — [CODEMAP.md](CODEMAP.md)

## Статус

Работает в проде. Каталог (поиск, фильтры, модалка, 3 языка), страница продавца
`?u=<ник>`, режим правки `?u=<ник>&edit=1` (общий ключ `EDIT_KEY`).
В работе (отдельные ветки, не в master):
- `worktree-seller-edit-auth` — вход продавца через Telegram вместо общего ключа, отметка «продана»;
- `worktree-add-new-listings` — автодобавление через Claude + Bot API, калькулятор «цена за партию», сравнение с розницей.

## Запуск локально

Сборки нет — это статика:

```sh
python3 -m http.server 8000   # http://localhost:8000/
```

`http://localhost` разрешён в CORS Worker'а, так что страница продавца и правки работают и локально.

## Тесты

```sh
./test.sh
```

Без сети и без ключей: `tests/test_catalog.py` проверяет данные `BGG`/`D` в `index.html`,
`worker/test/index.test.mjs` — Worker на моке KV (Node ≥ 20).

## Добавление игры

- Вручную/с Claude — по шагам из [CLAUDE.md](CLAUDE.md) (BGG ID только через поиск, не угадывать).
- Автоматически — GitHub Actions `Auto-add game listing` (`workflow_dispatch`): `auto_add.py`
  ищет игру на BGG, качает обложку (Tesera → Yandex), правит `index.html`, коммитит и деплоит.
  Зависимости скриптов — `pip install -r requirements.txt`.

## Деплой

- Сайт: `deploy.ps1` (Windows; токен Cloudflare в `~/.nastolki-token`, не в репо) или CI.
  На macOS то же самое руками: `dist/` = `index.html` + `covers/`, затем
  `npx wrangler pages deploy dist --project-name nastolki-catalog --branch main`.
- Worker: `cd worker && npx wrangler deploy`; секрет — `npx wrangler secret put EDIT_KEY`.
- Секреты CI: `CLOUDFLARE_API_TOKEN` в настройках репозитория.

## Структура

| Путь | Что это |
|---|---|
| `index.html` | весь фронтенд: CSS, JS, данные `BGG` (игры) и `D` (объявления) |
| `covers/{bgg_id}.webp` | обложки 300×300 |
| `worker/` | Cloudflare Worker `nastolki-api`: правки продавца и обложки в KV |
| `auto_add.py` | добавить/обновить объявление (используется CI) |
| `download_bgg_covers.py` | докачать недостающие обложки (BGG / Tesera / ручные ссылки) |
| `yandex_covers.py`, `add_listings.py`, `patch_catalog.py` | разовые скрипты, уже применены |
| `make_blueprint.json` | сценарий Make.com: канал → разбор LLM → запуск workflow (токен GitHub — плейсхолдер; в ветке `worktree-add-new-listings` его заменяет пайплайн на Bot API) |
| `blacklist.json` | продавцы, которых `auto_add.py` пропускает |
| `tests/`, `test.sh` | проверки |
