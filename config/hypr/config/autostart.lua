-- Auto-start config
-- if you dont use UWSM add your auto start programs here, otherwise use XDG autostart https://wiki.archlinux.org/title/XDG_Autostart

hl.on("hyprland.start", function()
  hl.exec_cmd("dbus-update-activation-environment --systemd --all")
  -- Аллокатор noctalia: инцидент 19.09 — за 3 дня VmData раздулся до 21.5 ГБ
  -- при RssAnon 100 МБ (инфляция арен glibc крупными транзиентами: образы
  -- буфера обмена ≤32 МиБ, декод 4K RGBA ~33 МБ). mmap_threshold фиксирован —
  -- это отключает динамический подъём до 32 МиБ (главный механизм «VmData
  -- растёт, RSS нет»): всё ≥1 МиБ живёт в mmap/munmap и сразу возвращается
  -- ОС; trim_threshold=2 МиБ возвращает вершины арен; arena_max=2 ограничивает
  -- число арен. Ряд роста: ~/.local/state/noctalia-leak/samples.log.
  -- Sacrifice loads separately; frame failures must not prevent shell startup.
  hl.exec_cmd("hyprpm reload -n; exec /home/q/.local/bin/noctalia-session")
  hl.exec_cmd("hyprctl plugin load /home/q/.local/lib/kitty-skins/mina-sacrifice-r2/libmina-sacrifice.so && hyprctl eval \"require('config.mina_frame').apply()\"")
  hl.exec_cmd("xhost +SI:localuser:root")
  -- Mark DP-3 as the XWayland primary output so Wine/UE5 games use 2560x1440
  -- instead of the ultrawide DP-2 for their "windowed fullscreen" size.
  hl.exec_cmd("sh -c 'sleep 2; xrandr --output DP-3 --primary'")

  -- Autostarted apps. Their workspace placement lives in windowrules.lua
  -- (all "silent", so nothing steals focus while they come up).
  local launch = "uwsm app -- "
  hl.exec_cmd(launch .. "discord")
  hl.exec_cmd(launch .. "/home/q/.local/bin/AyuGram")
  hl.exec_cmd(launch .. BROWSER)
  -- -silent = start into the tray without opening the main window.
  hl.exec_cmd(launch .. "steam -silent")
  -- Minimized to tray, and purely as an SDK client: the LED hardware and the
  -- saved profile belong to openrgb-server.service (pulled in by
  -- default.target), which also triggers noctalia-openrgb-sync.service for
  -- the first paint. Closing this window therefore no longer kills the sync.
  hl.exec_cmd(launch .. "openrgb --startminimized")
  -- Глобальное правило «окна моделей не видны»: переносит на скрытый
  -- воркспейс всё, что выросло из omp-сессий (см. windowrules.lua, слой 2).
  hl.exec_cmd("/home/q/.local/bin/hypr-agent-guard")
end)
