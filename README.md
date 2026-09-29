# speedtech-routing

Профиль маршрутизации [Happ](https://www.happ.su/) **SpeedTech**: всё идёт напрямую, через VPN — только то, что недоступно из России; реклама и телеметрия Windows блокируются.

## Как работает

| Что | Где | Как быстро доходит до пользователей |
|---|---|---|
| Большие списки (блокировки РКН, сервисы из v2fly, реклама) | `geosite.dat`, `geoip.dat` | Happ обновляет геофайлы не чаще раза в неделю |
| Наши правки `lists/proxy.txt`, `direct.txt`, `block.txt` | встраиваются прямо в профиль (JSON) | со следующим обновлением профиля |
| `lists/block-allow.txt` (разблокировать ложное срабатывание рекламы) | вычитается из `geosite.dat` | вместе с геофайлом |

Порядок правил (`RouteOrder: block-direct-proxy`): **блок → напрямую (наши исключения) → через VPN → всё остальное напрямую** (`GlobalProxy: false`).

### Категории `geosite.dat`

- `st-proxy` — runetfreedom `ru-blocked` + v2fly: `youtube`, `telegram`, `discord`, `openai`, `anthropic`, `category-ai-!cn`, `twitter`, `meta`, `facebook`, `instagram`, `github`, `google-play`, `spotify`.
- `st-direct` — v2fly `private`.
- `st-block` — v2fly `category-ads-all` + runetfreedom `win-spy` − `lists/block-allow.txt`.

### `geoip.dat`

Копия [runetfreedom `geoip-asn.dat`](https://github.com/runetfreedom/russia-blocked-geoip) (~165 КБ), кладётся в наш релиз.
В профиле используется только `geoip:telegram` (нужен для звонков Telegram). Локальные сети отдельно не нужны:
при `GlobalProxy: false` всё, что не попало в правила, и так идёт напрямую.

Свой маленький geoip (сотни байт) Happ не принимает — проверка геофайлов отвергает его как invalid,
поэтому используем готовый файл нормального размера. Режимы `--prepare-geoip` / `--geoip-dat` в `build.py`
оставлены для сборки через [v2fly/geoip](https://github.com/v2fly/geoip), если понадобится свой набор подсетей.

## Как добавить домен

1. Дописать строку в `lists/proxy.txt` (или `direct.txt` / `block.txt`). Синтаксис Xray: `example.com` = домен со всеми поддоменами, `full:`, `keyword:`, `regexp:`.
2. Закоммитить в `main`. GitHub Actions соберёт релиз за пару минут.
3. Профиль придёт пользователям со следующим обновлением подписки.

## Сборка

`python build/build.py --out dist` — Python 3.10+, без зависимостей. Источники — в `build/sources.json`.

GitHub Actions (`.github/workflows/build.yml`): раз в сутки (03:00 МСК), при пуше в `main` и вручную.
Релиз публикуется, только если что-то изменилось:
- изменились `lists/*` или шаблон профиля — сразу;
- изменились только внешние данные — не чаще раза в 7 дней (чаще Happ всё равно не скачает).

Каждый релиз — ветка `release` + тег `rYYYYMMDDHHMM`; в профиле ссылки на геофайлы закреплены на этот тег через jsDelivr.

## Файлы релиза

- `geosite.dat`, `geoip.dat` (+ `.sha256`)
- `profile.json` — профиль Happ
- `deeplink.txt` — `happ://routing/onadd/<base64>`
- `meta.json` — хэши, количество записей, размеры

Последний релиз: `https://raw.githubusercontent.com/Voldemar21/speedtech-routing/release/release/deeplink.txt`

## Лицензия и источники

GPL-3.0 (из-за данных runetfreedom). Источники и их лицензии — в [NOTICE.md](NOTICE.md).
