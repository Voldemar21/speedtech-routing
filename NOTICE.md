# Источники данных

| Источник | Что берём | Лицензия |
|---|---|---|
| [runetfreedom/russia-blocked-geosite](https://github.com/runetfreedom/russia-blocked-geosite) | `ru-blocked`, `win-spy` (текстовые списки из ветки `release`) | GPL-3.0 |
| [v2fly/domain-list-community](https://github.com/v2fly/domain-list-community) | категории сервисов, `category-ads-all`, `private` | MIT |
| [runetfreedom/russia-blocked-geoip](https://github.com/runetfreedom/russia-blocked-geoip) | `geoip-asn.dat` (ветка `release`) — копируется в наш релиз как `geoip.dat` без изменений | GPL-3.0 |
| [Telegram](https://core.telegram.org/resources/cidr.txt) | подсети Telegram (только для режима `--prepare-geoip`) | публичный список |

Подход к сборке без зависимостей вдохновлён [fwapbbs/devru-geosite](https://github.com/fwapbbs/devru-geosite) и
[hydraponique/roscomvpn-geosite](https://github.com/hydraponique/roscomvpn-geosite) (MIT).

Данные распространяются как есть, без гарантий точности.
