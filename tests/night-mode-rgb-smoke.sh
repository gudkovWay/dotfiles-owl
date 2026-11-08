#!/usr/bin/env bash
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export NIGHT_START=17:00 NIGHT_BOTTOM=21:00 NIGHT_RISE=04:00 NIGHT_END=06:30
export NIGHT_MIN_FACTOR=0.5832 NIGHT_RGB_STEP=0.01
export NIGHT_TEMP_DAY=6500 NIGHT_TEMP_NIGHT=4500
export NIGHT_DISPLAYS='Mi monitor:14;MAG 274QF X24:91:40'

check() {
    local time=$1 rgb=$2 factor=$3 temp=$4 xiaomi=$5 msi=$6 output
    output=$(bash "$REPO/config/hypr/scripts/night-mode.sh" print "$time")
    for expected in "rgb-factor: $rgb" "factor: $factor" "temp: $temp" \
        "display: Mi monitor -> $xiaomi" "display: MAG 274QF X24 -> $msi"; do
        if [[ $'\n'"$output"$'\n' != *$'\n'"$expected"$'\n'* ]]; then
            printf 'FAIL at %s: expected %s\n%s\n' "$time" "$expected" "$output" >&2
            exit 1
        fi
    done
}

check 12:00 1.000 1.000 identity 14 91
check 16:59 1.000 1.000 identity 14 91
check 17:00 1.000 1.000 identity 14 91
check 19:00 0.520 0.792 5500K 11 66
check 20:59 0.050 0.586 4510K 8 40
check 21:00 0.050 0.583 4500K 8 40
check 00:00 0.050 0.583 4500K 8 40
check 03:59 0.050 0.583 4500K 8 40
check 04:00 0.050 0.583 4500K 8 40
check 05:15 0.520 0.791 5500K 11 65
check 06:29 0.990 0.997 6486K 14 91
check 06:30 1.000 1.000 identity 14 91

# RGB's minimum must not depend on the monitor's calibrated night factor.
NIGHT_MIN_FACTOR=0.72 check 21:00 0.050 0.720 4500K 10 40
NIGHT_RGB_STEP=0.03 check 21:00 0.050 0.583 4500K 8 40
NIGHT_RGB_STEP=0.03 check 12:00 1.000 1.000 identity 14 91
printf 'PASS: 15 night RGB and monitor curve cases (print only; no hardware access)\n'
