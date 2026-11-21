# CODEMAP — nastolki-catalog (Boardex.am)

Читать первой. Карта модулей и потоков данных.

## Модули

```
index.html            один файл: <style> + разметка + один <script>
  ├─ TR{ru,en,hy}      строки интерфейса; setLang() → applyTR() → render()
  ├─ const BGG={…}     игры по названию-ключу: bgg_id, рейтинг, игроки, время, категории, image, bgg_url
  ├─ const D=[…]       объявления: t (ключ BGG), title, s (продавец), p, l, n, d, m (id сообщения TG), x (обмен)
  ├─ items             D → +_key="t|s|d", _b (исходные значения), фильтр по ?u=<ник>
  ├─ loadOverrides()   GET nastolki-api /overrides?seller=… → OV → applyOv() поверх items
  ├─ режим правки      ?u=<ник>&edit=1: renderEditor(), getEditKey() (localStorage), PUT /overrides, POST /img, POST /img/proxy
  ├─ filtered()/card()/render()   поиск, фильтры, сортировка, сетка; каждые 9 карточек — quoteCard()
  └─ openCard()/closeModal()     модалка; онбординг-подсказка (localStorage bgg-tip2)
covers/{bgg_id}.webp  обложки; fallback — BGG.image, затем эмодзи
worker/src/index.js   Cloudflare Worker nastolki-api, KV OVERRIDES
  ├─ GET  /overrides?seller=   публично
  ├─ PUT  /overrides           Bearer EDIT_KEY; key=t|s|d должен принадлежать seller; whitelist полей + валидация
  ├─ POST /img, GET/DELETE /img/<id>   обложки ≤ 60 КБ, тип по сигнатуре, id = sha256[:16]
  └─ POST /img/proxy           Bearer EDIT_KEY; скачать картинку по https-ссылке (обход CORS для canvas)
auto_add.py           CI: blacklist → поиск в D (t+s) → обновить или новый листинг (+BGG xmlapi2, обложка Tesera→Yandex) → переписать BGG/D в index.html
download_bgg_covers.py  ручная докачка обложек с выбором источника на игру
tests/test_catalog.py   инварианты данных BGG/D (регулярки те же, что в auto_add.py)
worker/test/          Worker на моке KV
```

## Потоки данных

1. **Новое объявление (автоматически).** Сообщение в канале → сценарий Make (`make_blueprint.json`,
   разбор LLM) → `workflow_dispatch` `add_game.yml` → `auto_add.py` правит `index.html` и `covers/`
   → проверка `tests/` → коммит boardex-bot → `wrangler pages deploy`.
2. **Новое объявление (вручную).** По CLAUDE.md: BGG ID через поиск → обложка → запись в `BGG` и `D` → коммит → `deploy.ps1`.
3. **Просмотр.** Браузер грузит статический `index.html`; на `?u=<ник>` дополнительно тянет правки продавца из Worker.
4. **Правка продавцом.** `?u=<ник>&edit=1` → ключ из prompt/localStorage → PUT в Worker → KV `seller:<ник>`
   → все посетители видят правку поверх `D` (исходные данные в `index.html` не меняются).

## Важные инварианты

- `D[i].t` == ключ в `BGG` (иначе карточка без обложки/рейтинга) — проверяет `tests/`.
- Ключ правки `t|s|d`: смена `t`, `s` или `d` в `D` «отвязывает» сохранённые в KV правки.
- `auto_add.py` и тесты находят данные регулярками `const BGG=(\{.*?\});` и `const D=(\[.*?\]);` —
  формат строк в `index.html` (одна строка JSON, без пробелов вокруг `=`) менять нельзя.
- Имена продавцов (`s`) лежат в открытом `index.html` и в публичном репо; на странице не выводятся.
