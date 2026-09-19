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

`install.sh` симлинкует каждый отслеживаемый конфиг-файл **по отдельности** в
`${XDG_CONFIG_HOME:-$HOME/.config}`: директории назначения остаются настоящими,
а уже живущие там runtime-файлы, которых нет в репозитории, не трогаются.
Симлинк, а не копия, и **никогда не затирание настоящего файла** на месте
ссылки — про такой печатается `WARN`. Что требует root (юниты в
`/etc/systemd/system`, udev-правила, демон пробуждения), скрипт не делает сам,
а печатает готовые команды.

Если в `~/.config` уже лежит настоящий файл с тем же путём, установщик его
не тронет — напечатает `WARN` и оставит как есть. Разовый перенос на
версию из репозитория (пример — `kitty/kitty.conf`):

```sh
diff ~/.config/kitty/kitty.conf config/kitty/kitty.conf
mv ~/.config/kitty/kitty.conf ~/.config/kitty/kitty.conf.local-bak
./install.sh
readlink -f ~/.config/kitty/kitty.conf   # убедиться, что это симлинк в репозиторий
rm ~/.config/kitty/kitty.conf.local-bak
```

Эта процедура — только для обычных конфигов из репозитория. Никогда не
применяйте её к app-native хранилищам токенов и к приватному хранилищу
ключей `~/.config/dotfiles-owl-private/`.

### Ключи: приватное хранилище

Секреты живут **вне репозитория**, в отдельной директории
`~/.config/dotfiles-owl-private/`. Fish-лоадер `config/fish/conf.d/api-keys.fish`
при старте молча читает оттуда сырые файлы ключей и экспортирует
`DEEPSEEK_API_KEY` и `ZAI_API_KEY`; нет файла или файл пуст — переменная просто
не выставляется.

```sh
mkdir -p ~/.config/dotfiles-owl-private/keys
chmod 700 ~/.config/dotfiles-owl-private ~/.config/dotfiles-owl-private/keys
touch ~/.config/dotfiles-owl-private/keys/deepseek ~/.config/dotfiles-owl-private/keys/zai
chmod 600 ~/.config/dotfiles-owl-private/keys/deepseek ~/.config/dotfiles-owl-private/keys/zai
micro ~/.config/dotfiles-owl-private/keys/deepseek   # вставить ключ в редакторе
micro ~/.config/dotfiles-owl-private/keys/zai
```

Значение ключа вводите в редакторе (`micro`, `nano`, …) или через
`read -s VAR && printf %s "$VAR" > файл` — не через `echo 'sk-…' > файл`,
иначе ключ останется в истории shell.

Реальные значения ключей **никогда не попадают в репозиторий** — ни в файлы,
ни в команды коммитов, ни в примеры из этого README. Вне репозитория остаются и
app-native хранилища токенов (token/auth store приложений): они относятся к
живой машине, а не к слепку конфигов.

### Проверка секретов

Pre-commit хук и Gitleaks ловят случайные ключи до и после коммита:

```sh
pre-commit install                     # включить pre-commit хук (стейдж проверяет он)
gitleaks dir .                         # текущие файлы
gitleaks git .                         # история репозитория
```

CI-сканирование (`.github/workflows/gitleaks.yml`) запускается на push и
pull_request — локальных проверок достаточно, чтобы не доводить до красного
пайплайна.
