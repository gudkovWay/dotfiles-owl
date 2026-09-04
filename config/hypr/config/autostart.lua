-- Auto-start config
-- if you dont use UWSM add your auto start programs here, otherwise use XDG autostart https://wiki.archlinux.org/title/XDG_Autostart

hl.on("hyprland.start", function ()
    hl.exec_cmd("dbus-update-activation-environment --systemd --all")
    hl.exec_cmd("noctalia")
    hl.exec_cmd("xhost +SI:localuser:root")
    -- Mark DP-3 as the XWayland primary output so Wine/UE5 games use 2560x1440
    -- instead of the ultrawide DP-2 for their "windowed fullscreen" size.
    hl.exec_cmd("sh -c 'sleep 2; xrandr --output DP-3 --primary'")

    -- Autostarted apps. Their workspace placement lives in windowrules.lua
    -- (all "silent", so nothing steals focus while they come up).
    local launch = "uwsm app -- "
    hl.exec_cmd(launch .. "discord")
    hl.exec_cmd(launch .. "AyuGram")
    hl.exec_cmd(launch .. "youtube-music-desktop-app")
    hl.exec_cmd(launch .. "zen-browser")
    -- -silent = start into the tray without opening the main window.
    hl.exec_cmd(launch .. "steam -silent")
    -- Minimized to tray, SDK server on for the Noctalia color sync, and the
    -- saved profile loaded immediately so no manual "Load profile" is needed.
    hl.exec_cmd(launch .. "openrgb --startminimized --server --profile purple")
    -- Paint the LEDs with the current Noctalia palette once OpenRGB is up. From
    -- then on the noctalia-openrgb-sync.path user unit handles palette changes.
    hl.exec_cmd("systemctl --user start noctalia-openrgb-sync.service")
end)
