#!/usr/bin/env python3
"""Гасит экраны и ждёт, пока демон скажет, что нажали пробел.

Запускается из monitors.sh, руками звать незачем. Разделение на этот клиент и
демон нужно из-за прав: читать /dev/input/event* сессия не может и не должна
(это был бы кейлоггер для любого процесса, запущенного от твоего имени), а
разговаривать с Hyprland может только она — сокет композитора лежит в её
$XDG_RUNTIME_DIR. Поэтому клавиатуру слушает демон под отдельным
пользователем, а гасит и зажигает экраны этот клиент.
Заодно гасит RGB-подсветку в ноль: сразу ПЕРЕД dpms off ставит маркер-файл
(SCREEN_OFF_RGB_LOCK) и запускает обычный sync палитры — sync видит маркер и
сам выдаёт 0%. Маркер живёт всю темноту, так что фоновые sync'и (палитра,
night mode) во тьме не зажгут подсветку. При любом выходе из темноты маркер
снимается перед финальным полным ре-синком — цвет заново берётся из палитры,
запоминать «прежнее» состояние подсветки не нужно. Если маркер снять не
успели (SIGKILL), снимет его monitors.sh on; SIGTERM сознательно пропускает
очистку — пришедший следом `off` должен остаться тёмным.

Тем же переходом уводит в тишину кулеры (тихий профиль ШИМ), останавливает
рендереры Wallpaper Engine и поднимает термосторож — всё это в
screen-off-extras.sh рядом; возврат делает он же в режиме wake.

Демон и его установка — в wake-on-space-daemon/ рядом.

    wake-on-space.py --probe   проверить, что демон отвечает (код 0/1)
    wake-on-space.py           погасить и ждать пробел
"""

import argparse
import os
import select
import socket
import subprocess
import sys
import time

SOCKET_PATH = "/run/wake-on-space/sock"
HYPRCTL = "hyprctl"
CONNECT_TIMEOUT = 2
POLL_TIMEOUT = 5
# Подсветка на время темноты: скрипт, умеющий проталкивать палитру в OpenRGB.
# Тот же скрипт без переменной окружения возвращает полную яркость —
# отдельного «восстановления состояния» не требуется.
RGB_SYNC = os.path.join(os.path.dirname(os.path.realpath(__file__)),
                        "noctalia-openrgb-sync.sh")
# Маркер «экраны погашены»: путь переопределяемый, тот же, что в
# noctalia-openrgb-sync.sh и monitors.sh. Пока файл существует, sync держит
# подсветку на 0%, чем бы его ни дёргали фоном.
SCREEN_OFF_RGB_LOCK = os.environ.get(
    "SCREEN_OFF_RGB_LOCK",
    os.path.join(os.environ.get("XDG_RUNTIME_DIR", "/tmp"),
                 "screen-off-rgb.lock"))
# Экстра-переход тьмы: кулеры в тихий профиль, термосторож, старт/стоп обоев.
# Вызов синхронный — клиент живёт в transient-юните, который systemd вычищает
# на выходе, и фоновый ребёнок не пережил бы клиента, — но с таймаутом:
# зависший экстра-скрипт не должен задерживать ни гашение, ни пробуждение.
# Скрипта нет — молча продолжаем без него (как и с подсветкой).
SCREEN_OFF_EXTRAS = os.path.join(os.path.dirname(os.path.realpath(__file__)),
                                 "screen-off-extras.sh")
EXTRAS_TIMEOUT = 5


def rgb_lock_create():
    """Поставить маркер тьмы (0% подсветки для всех sync'ов)."""
    try:
        with open(SCREEN_OFF_RGB_LOCK, "w"):
            pass
    except OSError:
        pass


def rgb_lock_remove():
    """Снять маркер тьмы перед восстановлением подсветки."""
    try:
        os.unlink(SCREEN_OFF_RGB_LOCK)
    except OSError:
        pass


def screen_off_extras(mode):
    """Переход тьмы («dark») или пробуждения («wake»): кулеры, обои, сторож."""
    if not os.access(SCREEN_OFF_EXTRAS, os.X_OK):
        return
    try:
        subprocess.run([SCREEN_OFF_EXTRAS, mode], timeout=EXTRAS_TIMEOUT,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except subprocess.TimeoutExpired:
        print(f"screen-off-extras {mode}: не уложился в {EXTRAS_TIMEOUT} с",
              file=sys.stderr)


def hypr(lua):
    subprocess.run([HYPRCTL, "eval", lua],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def dpms_is_on():
    out = subprocess.run([HYPRCTL, "-j", "monitors"],
                         capture_output=True, text=True).stdout
    return '"dpmsStatus": true' in out


def rgb_sync(wait=False):
    """Протолкнуть палитру в OpenRGB; яркость решает сам sync-скрипт: с
    маркером тьмы — 0%, без него — обычная палитра.

    По умолчанию неблокирующе (wait=False -> Popen): подсветка — косметика, и
    ожидание SDK-сервера внутри скрипта (до минуты, если тот лежит) не должно
    задерживать ни гашение, ни пробуждение. wait=True дожидается завершения
    запущенного sync перед возвратом — это обязателен для финального
    восстановления в finally: watcher живёт в transient-юните, и systemd
    вычищает его cgroup, как только MainPID выйдет, — не дождавшись, мы можем
    убить восстанавливающий sync на полпути. Очерёдность своих запусков
    страхована flock'ом в самом скрипте; нет скрипта — нет и подсветки, молча
    продолжаем без неё (возвращаем None).
    """
    if not os.access(RGB_SYNC, os.X_OK):
        return None
    proc = subprocess.Popen([RGB_SYNC],
                            stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL)
    if wait:
        proc.wait()
    return proc


class Lines:
    """Построчное чтение из сокета с таймаутом.

    sock.makefile() для этого не годится: первый же таймаут навсегда взводит
    внутри SocketIO флаг, и все следующие чтения падают с
    OSError("cannot read from timed out object"). А ждать с таймаутом
    приходится, чтобы успевать проверять, не зажгли ли экраны иначе.
    """

    def __init__(self, sock):
        self.sock = sock
        self.buf = b""

    def readline(self, timeout):
        """Строка без \\n, "" если демон закрыл сокет, None если таймаут."""
        deadline = time.monotonic() + timeout
        while True:
            nl = self.buf.find(b"\n")
            if nl >= 0:
                line, self.buf = self.buf[:nl], self.buf[nl + 1:]
                return line.decode("utf-8", "replace").strip()
            left = deadline - time.monotonic()
            if left <= 0 or not select.select([self.sock], [], [], left)[0]:
                return None
            chunk = self.sock.recv(4096)
            if not chunk:
                return ""
            self.buf += chunk


def connect():
    """Подключается к демону и ждёт от него подтверждения готовности."""
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    sock.settimeout(CONNECT_TIMEOUT)
    sock.connect(SOCKET_PATH)
    # Дальше ждём через select, поэтому сам сокет возвращаем в блокирующий
    # режим: recv зовётся только когда данные уже есть.
    sock.settimeout(None)
    lines = Lines(sock)
    reply = lines.readline(CONNECT_TIMEOUT)
    if reply != "armed":
        sock.close()
        raise OSError(f"демон ответил {reply!r}")
    return sock, lines


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--probe", action="store_true",
                    help="только проверить, что демон готов слушать клавиатуру")
    args = ap.parse_args()

    try:
        sock, lines = connect()
    except OSError as err:
        print(f"демон недоступен: {err}", file=sys.stderr)
        return 1
    if args.probe:
        sock.close()
        return 0

    # Гасим только после того, как демон подтвердил готовность: иначе между
    # гашением и открытием клавиатур был бы промежуток, в котором нажатый
    # пробел пропал бы, и экраны остались бы тёмными.
    #
    # Маркер тьмы ставим перед dpms off, но уже после готовности демона:
    # с этой секунды любой sync держит подсветку на 0%, затемняющий — в том
    # числе все, что прилетят фоном, пока экраны погашены.
    rgb_lock_create()
    hypr('hl.dispatch(hl.dsp.dpms("off"))')
    # Экраны погасли — можно гасить шум: тихий профиль кулеров, стоп обоев,
    # термосторож. Маркер тьмы уже стоит, поэтому сторож не выйдет сам.
    screen_off_extras("dark")
    dim = rgb_sync()

    try:
        while True:
            try:
                line = lines.readline(POLL_TIMEOUT)
            except OSError:
                line = ""

            if line is None:
                # Экраны могли зажечь иначе — этим же скриптом с `on`, из tty,
                # по ssh. Тогда ждать больше нечего.
                if dpms_is_on():
                    return 0
                continue

            if line == "space":
                hypr('hl.dispatch(hl.dsp.dpms("on"))')
                return 0
            if line in ("", "no-keyboards"):
                # Демон умер или у него не осталось клавиатур: будить нечем,
                # поэтому зажигаем сами, а не оставляем экраны тёмными.
                hypr('hl.dispatch(hl.dsp.dpms("on"))')
                return 1
            # Что-то незнакомое от демона — не повод зажигать экраны, ждём
            # дальше.
    finally:
        # Сюда приходим при каждом выходе из темноты: пробел, чужой `on`,
        # смерть демона. Первым делом — экстра-переход: сторож убивается
        # насмерть (иначе он успеет эскалировать уже после возврата кривой),
        # кулеры уходят под BIOS-кривую, обои встают. Затем снимаем маркер
        # тьмы — иначе восстанавливающий ре-синк тоже увидит 0% — и
        # дожидаемся своего затемнения, чтобы возврат не перегнался с ним
        # (возврат из monitors.sh `on` и палитрный sync подстрахованы flock'ом
        # в самом скрипте). SIGTERM/SIGKILL намеренно сюда не попадают:
        # неубранный маркер оставляет следующий `off` тёмным, а прибрать его
        # успеет monitors.sh on.
        screen_off_extras("wake")
        rgb_lock_remove()
        # Keep DDC work outside the waker's cgroup and off the wake critical path.
        try:
            restored = subprocess.run(
                ["systemctl", "--user", "start", "--no-block",
                 "night-mode-restore.service"], timeout=2)
            if restored.returncode:
                print("night-mode restore could not be enqueued", file=sys.stderr)
        except (OSError, subprocess.TimeoutExpired) as err:
            print(f"night-mode restore could not be enqueued: {err}", file=sys.stderr)
        if dim is not None and dim.poll() is None:
            dim.wait()
        # Финальное восстановление — только синхронно: watcher живёт в
        # transient-юните, и systemd удаляет его cgroup, как только MainPID
        # выйдет. Если не дождаться, cgroup заберёт восстанавливающий sync
        # вместе с юнитом — и подсветка останется чёрной.
        rgb_sync(wait=True)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(130)
