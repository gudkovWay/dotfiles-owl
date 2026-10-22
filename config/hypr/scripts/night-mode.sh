#!/usr/bin/env bash
# Ночной режим: плавная рампа яркости мониторов (ddcutil, VCP 0x10),
# тёплый оттенок (ShojiWM: native shoji_native.py; Hyprland: hyprsunset
# через IPC) и затемнение LED.
#
# Почему так:
#  * Движок — systemd-таймер, раз в минуту. Скрипт делает ровно один проход
#    и выходит: никакого внутреннего сна, чтобы юнит оставался oneshot и
#    переживал рестарты без риска задвоения процессов.
#  * «Последнее применённое» хранится в файле-стейте: между тиками процеcc
#    умирает, поэтому память можно держать только на диске. Квантование
#    (шаг фактора и температуры) нужно именно ради этого файла — оно
#    гарантирует, что в тихие минуты тик не дёргает железо вообще.
#  * Всё применение завёрнуто в «применять только изменение»: упавший
#    ddcutil не ломает ход — на следующем тике значение останется
#    «неприменённым» и повторится само.
#  * Файл-фактор для LED-синка пишется по общему контракту: одна строка
#    `%.3f`, 1.000 = день. Драйвер — единственный писатель; читает его
#    только noctalia-openrgb-sync.sh.
#
# Тестирование — только через PATH-стабы (fake ddcutil/hyprctl/синк),
# живое железо здесь не трогается.
set -euo pipefail

# --- Конфиг (env-переменные с дефолтами) ------------------------------------
# Границы кривой, минуты суток. Спуск идёт ЧЕРЕЗ полночь: NIGHT_START ->
# полночь -> NIGHT_BOTTOM, затем дно ДЕРЖИТСЯ до NIGHT_RISE, и только потом
# начинается подъём до NIGHT_END. Поэтому интервалы считаются в модульной
# арифметике +1440, а не «наивным» сравнением минут.
NIGHT_START="${NIGHT_START:-18:00}"      # начало спуска
NIGHT_BOTTOM="${NIGHT_BOTTOM:-22:00}"    # момент достижения дна
NIGHT_RISE="${NIGHT_RISE:-03:30}"        # конец удержания дна, начало подъёма
NIGHT_END="${NIGHT_END:-06:00}"          # возврат к 100%
NIGHT_MIN_FACTOR="${NIGHT_MIN_FACTOR:-0.72}"
NIGHT_TEMP_DAY="${NIGHT_TEMP_DAY:-6500}"
NIGHT_TEMP_NIGHT="${NIGHT_TEMP_NIGHT:-4500}"
NIGHT_TEMP_STEP="${NIGHT_TEMP_STEP:-50}" # квант температуры, K
NIGHT_RGB_STEP="${NIGHT_RGB_STEP:-0.01}" # квант фактора для LED
# Пары "модель монитора:база", разделённые «;». Модель — как в `ddcutil
# detect` (EDID Model), выбор дисплея идёт через `ddcutil --model`: он не
# зависит от порядка нумерации i2c-шин после ребута. База — дневная яркость
# по шкале VCP 0..100; ночная цель = round(база * фактор).
# Шкалы VCP у мониторов несравнимы (MSI при 70 визуально темнее Xiaomi при
# 14). Базы 91/14 и дно 0.72 заданы хозяином вечером 18.09 от текущей
# яркости (70/11): день +30%, дно -5%. Xiaomi — пресет User1 (50/47/44,
# слегка тёплый), глубже гейны правятся только OSD (DDC лочит).
NIGHT_DISPLAYS="${NIGHT_DISPLAYS:-Mi monitor:14;MAG 274QF X24:91}"
# Путь к LED-синку: по умолчанию сосед по каталогу — оба скрипта живут
# вместе, и переезд каталога не должен рвать связь.
NIGHT_RGB_SYNC="${NIGHT_RGB_SYNC:-$(dirname "$0")/noctalia-openrgb-sync.sh}"

STATE_FILE="${XDG_RUNTIME_DIR:-/tmp}/night-mode.last"
FACTOR_FILE="${XDG_STATE_HOME:-$HOME/.local/state}/night-mode/factor"

# --- Вспомогательные функции -------------------------------------------------

# "HH:MM" -> минуты с полуночи. Ошибка формата = ошибка конфига, молчать
# нельзя: тихий выход оставил бы мониторы в ночном состоянии на весь день.
to_min() {
    local t="$1"
    [[ $t =~ ^([0-9]{1,2}):([0-9]{2})$ ]] || {
        printf 'night-mode: bad time %q\n' "$t" >&2
        return 1
    }
    local h=${BASH_REMATCH[1]} m=${BASH_REMATCH[2]}
    (( 10#$h < 24 && 10#$m < 60 )) || {
        printf 'night-mode: bad time %q\n' "$t" >&2
        return 1
    }
    echo $(( 10#$h * 60 + 10#$m ))
}

# Вычислить (фактор, температуру) для минуты суток. Эхо двух строк:
# фактор и целевую температуру (или слово identity, если день).
# Вся математика — в целых числах: квантование всё равно целочисленное,
# а дробная арифметика в bash только добавила бы зависимости.
curve() {
    local now=$1
    local start bottom rise end
    start=$(to_min "$NIGHT_START")
    bottom=$(to_min "$NIGHT_BOTTOM")
    rise=$(to_min "$NIGHT_RISE")
    end=$(to_min "$NIGHT_END")

    # Приводим всё к одной оси «от старта»: точка ночи, чья минута суток
    # меньше старта, лежит на СЛЕДУЮЩИЕ сутки (+1440); большая — в те же
    # (22:00 при старте 18:00). Между NIGHT_END и NIGHT_START — день.
    local ax
    ax() { if (( $1 > start )); then echo "$1"; else echo $(( $1 + 1440 )); fi; }
    local bot_low rise_at end_at
    bot_low=$(ax "$bottom")
    rise_at=$(ax "$rise")
    end_at=$(ax "$end")

    local t
    if (( now >= start )); then
        t=$now
    elif (( now < end )); then
        t=$(( now + 1440 ))
    else
        echo "1.000"; echo "identity"; return
    fi

    local span frac_num
    if (( t < bot_low )); then
        # Спуск: start -> дно. Фактор падает от 1 к минимуму, температура —
        # от дневной к ночной.
        span=$(( bot_low - start ))
        frac_num=$(( (t - start) * 1000 / span )) # 0..1000, тысячные
        emit "down" "$frac_num"
    elif (( t < rise_at )); then
        # Удержание дна: минимум и ночная температура без движения —
        # отдельный сегмент, чтобы подъём не начинался раньше NIGHT_RISE.
        # Дно = спуск, дошедший до конца (frac=1000): тот же emit, без
        # дублирования форматирования.
        emit "down" 1000
    else
        # Подъём: rise -> end на общей оси.
        span=$(( end_at - rise_at ))
        frac_num=$(( (t - rise_at) * 1000 / span ))
        emit "up" "$frac_num"
    fi
}

# По направлению (down|up) и доле интервала (0..1000) эхо фактора и
# целевой температуры (или слова identity: температура не ниже дневной
# означает «CTM отключён», даже внутри первого мига спуска).
emit() {
    local dir=$1 frac_num=$2
    local min_f
    min_f=$(awk -v x="$NIGHT_MIN_FACTOR" 'BEGIN{ printf "%.0f", x*1000 }')
    local f_num
    if [[ $dir == down ]]; then
        f_num=$(( 1000 - (1000 - min_f) * frac_num / 1000 ))
    else
        f_num=$(( min_f + (1000 - min_f) * frac_num / 1000 ))
    fi
    awk -v f="$f_num" -v d="$NIGHT_TEMP_DAY" -v n="$NIGHT_TEMP_NIGHT" \
        -v frac="$frac_num" -v dir="$dir" 'BEGIN{
        printf "%.3f\n", f/1000
        if (dir == "down") t = d + (n - d) * frac / 1000
        else               t = n + (d - n) * frac / 1000
        if (t >= d) print "identity"
        else printf "%.0f\n", t
    }'
}

# --- Режим print --------------------------------------------------------------
if [[ ${1:-} == print ]]; then
    now_min=$(to_min "${2:-$(date +%H:%M)}")
    readarray -t res < <(curve "$now_min")
    echo "factor: ${res[0]}"
    if [[ ${res[1]} == identity ]]; then
        echo "temp: identity"
    else
        echo "temp: ${res[1]}K"
    fi
    IFS=';' read -ra displays <<<"$NIGHT_DISPLAYS"
    for pair in "${displays[@]}"; do
        spec=${pair%:*}
        base=${pair##*:}
        target=$(awk -v b="$base" -v f="${res[0]}" 'BEGIN{ printf "%.0f", b*f }')
        echo "display: $spec -> $target"
    done
    exit 0
fi

# --- Применение (один проход) --------------------------------------------------
now_min=$(to_min "$(date +%H:%M)")
readarray -t res < <(curve "$now_min")
# Пустой вывод curve = сломанный конфиг времён (to_min уже кричал в stderr).
# Без guard пустой фактор превратился бы в 0.000: LED гаснут, мониторы в ноль.
(( ${#res[@]} == 2 )) || { printf 'night-mode: curve failed\n' >&2; exit 1; }
factor=${res[0]}
temp_target=${res[1]}

# Квантование фактора для LED: шаг нужен, чтобы файл-фактор и вызов синка
# менялись редко и предсказуемо, а не на каждом тике из-за шума округления.
rgb_factor=$(awk -v f="$factor" -v s="$NIGHT_RGB_STEP" 'BEGIN{
    printf "%.3f", int(f / s + 0.0001) * s + 0
}')
# Квантование температуры до NIGHT_TEMP_STEP, кроме дня (день = identity).
if [[ $temp_target == identity ]]; then
    temp_action="identity"
else
    temp_action=$(awk -v t="$temp_target" -v s="$NIGHT_TEMP_STEP" 'BEGIN{
        printf "%.0f", int(t / s + 0.5) * s
    }')
fi

# Стейт «последнее применённое». С guard на source: файл в XDG_RUNTIME_DIR,
# но привычка сорсить без проверки — источник неприятностей.
last_applied() {
    local key=$1
    [[ -r $STATE_FILE ]] || return 1
    # Имя ключа формируем сами, значения берём только из KEY=VAL-строк.
    local line
    line=$(sed -n "s/^${key}=//p" "$STATE_FILE" | head -n1)
    [[ -n $line ]] || return 1
    echo "$line"
}

mkdir -p "$(dirname "$STATE_FILE")"
touch "$STATE_FILE"

# --- a) LED: файл-фактор + вызов синка ----------------------------------------
if [[ $(last_applied FACTOR || true) != "$rgb_factor" ]]; then
    mkdir -p "$(dirname "$FACTOR_FILE")"
    printf '%.3f\n' "$rgb_factor" >"$FACTOR_FILE"
    if "$NIGHT_RGB_SYNC"; then
        sed -i '/^FACTOR=/d' "$STATE_FILE"
        echo "FACTOR=$rgb_factor" >>"$STATE_FILE"
    else
        # Синк упал — факт применения не фиксируем: следующий тик повторит.
        printf 'night-mode: RGB sync failed\n' >&2
    fi
fi

# --- b) Мониторы ---------------------------------------------------------------
IFS=';' read -ra displays <<<"$NIGHT_DISPLAYS"
for pair in "${displays[@]}"; do
    spec=${pair%:*}
    base=${pair##*:}
    target=$(awk -v b="$base" -v f="$factor" 'BEGIN{ printf "%.0f", b*f }')
    key="DISPLAY:${spec}"
    failkey="DDCFAIL:${spec}"
    if [[ $(last_applied "$key" || true) != "$target" ]]; then
        # Модель монитора содержит пробелы — передаём как один аргумент,
        # чтобы она не разрывалась на слова.
        #
        # Ошибку ddcutil (трейс стека на ~80 строк: EIO на i2c-шине и т.п.)
        # в журнал даём только при ПЕРВОЙ неудаче для этого целевого
        # значения: тик повторяет setvcp каждую минуту, и без затейки каждый
        # повтор плескал бы трейс заново — файлы журнала ротировались за
        # часы (инцидент 19.09: 4083 строки ddcutil на 25 минут архива).
        # Успех или смена цели затейку снимает: новая серия сбоев снова
        # станет заметной. Ретраи при этом не меняются — только тишина.
        if err=$(ddcutil --model "$spec" setvcp 10 "$target" 2>&1); then
            sed -i "/^${key}=/d;/^${failkey}=/d" "$STATE_FILE"
            echo "${key}=${target}" >>"$STATE_FILE"
        elif [[ $(last_applied "$failkey" || true) != "$target" ]]; then
            printf 'night-mode: ddcutil failed for %s (target %s):\n%s\n' \
                "$spec" "$target" "$err" >&2
            echo "${failkey}=$target" >>"$STATE_FILE"
        fi
    fi
done

# --- c) Температура -------------------------------------------------------------
# Температура применяется КАЖДЫЙ тик безусловно, в отличие от ddcutil и LED:
# бэкенд могут перезапустить или пережить ребут, его CTM слетит к дефолту,
# а стейт «уже применено» этого не заметит. Повторная установка того же
# значения раз в минуту дешева: native сам пропускает идентичное аппаратное
# состояние, а жизненный цикл (пересоздание выхода, смена режима, resume,
# включение) инвалидирует применённое.
#
# Бэкенд выбирается по фактическому XDG_CURRENT_DESKTOP (в manager-окружении
# таймера он корректен): точный токен ShojiWM — native CLI, точный токен
# Hyprland — hyprctl hyprsunset. Ни один не распознан — наблюдаемый провал,
# без догадок по HYPRLAND_INSTANCE_SIGNATURE и без || true: провал больше
# не маскируется. Ошибку печатаем только при ПЕРВОМ провале серии
# (бэкенд+сессия+цель, ключ TEMPFAIL в STATE_FILE по образцу DDCFAIL):
# таймер тикает раз в минуту, и без затейки повторный провал заполнял бы
# журнал. Успех или явный deferred серию снимает; повтор той же серии
# молчит, но выход остаётся ненулевым.
NATIVE_PY="$HOME/.local/libexec/shojiwm/tools/shoji_native.py"
desktops=":${XDG_CURRENT_DESKTOP:-}:"
temp_ok=false
temp_error=""
if [[ $desktops == *":ShojiWM:"* ]]; then
    temp_backend="shojiwm"
    if [[ $temp_action == identity ]]; then
        temp_args=(identity)
    else
        temp_args=(temperature "$temp_action")
    fi
    # Успех — только по коду выхода; вывод (включая явный deferred) —
    # диагностика, а не признак применения.
    if temp_error=$(/usr/bin/python3 "$NATIVE_PY" "${temp_args[@]}" 2>&1); then
        temp_ok=true
    elif [[ -z $temp_error ]]; then
        temp_error="native CLI завершился с ненулевым кодом без вывода"
    fi
elif [[ $desktops == *":Hyprland:"* ]] && command -v hyprctl >/dev/null 2>&1; then
    temp_backend="hyprland"
    # Успех — только по коду выхода hyprctl; exit 0 с warning в stderr
    # провалом не считается, но текст печатаем как диагностику.
    if [[ $temp_action == identity ]]; then
        if temp_error=$(hyprctl hyprsunset identity 2>&1 >/dev/null); then
            temp_ok=true
        else
            temp_error="hyprctl hyprsunset identity: $temp_error"
        fi
    else
        if temp_error=$(hyprctl hyprsunset temperature "$temp_action" 2>&1 >/dev/null); then
            temp_ok=true
        else
            temp_error="hyprctl hyprsunset temperature $temp_action: $temp_error"
        fi
    fi
else
    temp_backend="none"
    temp_error="night-mode: не распознан бэкенд температуры (XDG_CURRENT_DESKTOP=${XDG_CURRENT_DESKTOP:-<пусто>}); нужен ShojiWM (native) или Hyprland (hyprctl)"
fi

if [[ $temp_ok == true ]]; then
    # Успех или явный deferred: серию сбоев снимаем. Диагностику из вывода
    # (например, deferred native) печатаем, но железом это не считаем.
    sed -i '/^TEMPFAIL=/d' "$STATE_FILE"
    [[ -z $temp_error ]] || printf 'night-mode: temperature diagnostic:\n%s\n' \
        "$temp_error" >&2
    exit 0
fi

temp_series="${temp_backend}:${WAYLAND_DISPLAY:-}:${temp_action}"
if [[ $(last_applied TEMPFAIL || true) != "$temp_series" ]]; then
    printf 'night-mode: temperature failed (%s):\n%s\n' \
        "$temp_series" "$temp_error" >&2
    # Сначала снимаем старый ключ: last_applied читает первую строку, и без
    # удаления при смене цели старая серия осталась бы первой — новая серия
    # каждый тик считалась бы новой и заливала бы журнал.
    sed -i '/^TEMPFAIL=/d' "$STATE_FILE"
    echo "TEMPFAIL=$temp_series" >>"$STATE_FILE"
fi
exit 1
