#!/usr/bin/env python3
"""Гасит экраны и ждёт, пока демон скажет, что нажали пробел.

Запускается из monitors.sh, руками звать незачем. Разделение на этот клиент и
демон нужно из-за прав: читать /dev/input/event* сессия не может и не должна
(это был бы кейлоггер для любого процесса, запущенного от твоего имени), а
разговаривать с Hyprland может только она — сокет композитора лежит в её
$XDG_RUNTIME_DIR. Поэтому клавиатуру слушает демон под отдельным
пользователем, а гасит и зажигает экраны этот клиент.

Демон и его установка — в wake-on-space-daemon/ рядом.

    wake-on-space.py --probe   проверить, что демон отвечает (код 0/1)
    wake-on-space.py           погасить и ждать пробел
"""

import argparse
import socket
import subprocess
import sys

SOCKET_PATH = "/run/wake-on-space/sock"
HYPRCTL = "hyprctl"


def hypr(lua):
    subprocess.run([HYPRCTL, "eval", lua],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def dpms_is_on():
    out = subprocess.run([HYPRCTL, "-j", "monitors"],
                         capture_output=True, text=True).stdout
    return '"dpmsStatus": true' in out


def connect():
    """Подключается к демону и ждёт от него подтверждения готовности."""
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    sock.settimeout(2)
    sock.connect(SOCKET_PATH)
    reply = sock.makefile("r").readline().strip()
    if reply != "armed":
        sock.close()
        raise OSError(f"демон ответил {reply!r}")
    return sock


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--probe", action="store_true",
                    help="только проверить, что демон готов слушать клавиатуру")
    args = ap.parse_args()

    try:
        sock = connect()
    except (OSError, socket.timeout) as err:
        print(f"демон недоступен: {err}", file=sys.stderr)
        return 1
    if args.probe:
        sock.close()
        return 0

    # Гасим только после того, как демон подтвердил готовность: иначе между
    # гашением и открытием клавиатур был бы промежуток, в котором нажатый
    # пробел пропал бы, и экраны остались бы тёмными.
    hypr('hl.dispatch(hl.dsp.dpms("off"))')

    stream = sock.makefile("r")
    while True:
        sock.settimeout(5)
        try:
            line = stream.readline().strip()
        except socket.timeout:
            # Экраны могли зажечь иначе — этим же скриптом с `on`, из tty, по
            # ssh. Тогда ждать больше нечего.
            if dpms_is_on():
                return 0
            continue
        except OSError:
            line = ""

        if line == "space":
            hypr('hl.dispatch(hl.dsp.dpms("on"))')
            return 0
        if line in ("", "no-keyboards"):
            # Демон умер или у него не осталось клавиатур: будить нечем,
            # поэтому зажигаем сами, а не оставляем экраны тёмными.
            hypr('hl.dispatch(hl.dsp.dpms("on"))')
            return 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(130)
