# dotfiles-owl

Рабочий стол машины `owl`: CachyOS, Hyprland на Lua-конфиге, оболочка
[Noctalia](https://github.com/noctalia-dev/noctalia-shell).

Не общий шаблон, а слепок одной живой машины — с двумя мониторами, геймпадом,
локальной LLM и подсветкой, которая красится от обоев.

## Раскладка

```
config/          всё, что уезжает в ~/.config
  hypr/          Hyprland на Lua: config/*.lua, скрипты, плагин ai-triage
  fish kitty alacritty noctalia zed micro yazi rofi btop lazygit …
  vader5/        конфиг драйвера геймпада (Numpad 1-6 на доп. кнопках)
  llama-cpp/     список локальных моделей для qwen-serve
  OpenRGB/       профиль и раскладка устройств (без логов)
systemd/user/    ai-embed, ai-journal + таймер
system/          юниты и udev-правила, которым нужен root
local/bin/       qwen-serve, qwen-watch — обвязка локальной модели
claude/          settings.json, CLAUDE.md, хук про трейлеры в коммитах
vendor/          сабмодули: то, что вынесено в свои публичные репозитории
install.sh
```

## Что вынесено отдельно

Два куска самодостаточны и живут своими публичными репозиториями, а сюда
приходят сабмодулями:

- [noctalia-gamepad-launcher](https://github.com/gudkovWay/noctalia-gamepad-launcher)
  — лаунчер игр, открывается тряской геймпада
- [noctalia-openrgb-sync](https://github.com/gudkovWay/noctalia-openrgb-sync)
  — палитра Noctalia уезжает в подсветку

`ai-triage` остался здесь: он завязан на `~/storage/ai` и отдельно не живёт.

## Из чего это состоит, если по существу

**Hyprland на Lua, а не на `hyprland.conf`.** `config/*.lua` — семнадцать
файлов по темам, от `binds` до `gaming`. Обычный `hyprland.conf` в репозитории
тоже лежит, но живой конфиг собирается из Lua.

**Гашение экранов с пробуждением только пробелом.**
`config/hypr/scripts/wake-on-space-daemon/` — демон под отдельным пользователем
`screenwake`, читает устройства ввода вне сессии, потому что бинды Hyprland при
DPMS off уже мертвы. Ставится своим `install.sh`, слушает unix-сокет с правами
на группу.

**Геймпад Flydigi Vader 5 Pro.** `config/vader5/config.toml` отдаёт шесть
дополнительных кнопок как Numpad 1-6 — не F13-F18, у тех нет скан-кода PC/AT и
сквозь Wine они не проходят. Драйвер — форк
[flydigi-vader5](https://github.com/gudkovWay/flydigi-vader5), ветка
`q/numpad-extras`.

**Локальная модель.** `local/bin/qwen-serve` поднимает llama-server по записи
из `config/llama-cpp/models.ini`; `qwen-watch` смотрит за ним. Стенд агента,
который этим пользуется, — в отдельном репозитории `ai-stand`.

## Установка

```sh
git clone --recurse-submodules git@github.com:gudkovWay/dotfiles-owl.git ~/dev/dotfiles-owl
cd ~/dev/dotfiles-owl
./install.sh --dry-run    # посмотреть, что будет сделано
./install.sh
```

`install.sh` симлинкует, а не копирует, и **никогда не затирает настоящий
файл** на месте ссылки — про такой печатает `WARN`. Что требует root (юниты в
`/etc/systemd/system`, udev-правила, демон пробуждения) он не делает сам, а
печатает готовые команды.
