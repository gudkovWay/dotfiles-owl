hl.config({
    dwindle = {
        preserve_split = true,
    },
    misc = {
        col = {
            splash = CACHYLGREEN,
        },
        -- Пробуждение экранов по вводу выключено намеренно: погашенные
        -- через scripts/monitors.sh экраны будит только пробел, который ловит
        -- scripts/wake-on-space.py напрямую из evdev. Поставить сюда true — и
        -- экраны будут загораться от любого движения мыши, включая то самое,
        -- которым их только что погасили.
        -- key_press_enables_dpms скрипт временно включает сам, если демону не
        -- дали доступ к клавиатуре: тогда будит любая клавиша — это хуже, но
        -- лучше, чем тёмные экраны, которые нечем зажечь.
        -- Оговорка: если когда-нибудь включить в Noctalia режим простоя
        -- «screen off», гасить будет он, и будить — тоже ему (по своему
        -- resume), пробел тут ни при чём.
        mouse_move_enables_dpms = false,
        key_press_enables_dpms = false,
        middle_click_paste = false,
        enable_swallow = true,
        swallow_regex = "(kitty|ghostty|[Kk]onsole|Alacritty|gnome-terminal|xfce[0-9]?-terminal)",
        vrr = 3,
    },
    xwayland = {
        force_zero_scaling = true
    },
    ecosystem = {
        no_update_news = true,
        no_donation_nag = true,
    },
})