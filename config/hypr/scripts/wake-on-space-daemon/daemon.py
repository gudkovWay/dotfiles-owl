#!/usr/bin/env python3
"""Демон пробуждения экранов по пробелу.

Умеет ровно одно: сказать подключившемуся клиенту, что нажали пробел. Ни
какие ещё клавиши нажимали, ни что с ними делать — он не сообщает и не знает.

ЗАЧЕМ ОН ВООБЩЕ НУЖЕН. Пока DPMS выключен, Hyprland не обрабатывает бинды
вовсе (проверено на живой сессии: сабмап активен, бинд на пробел в нём
зарегистрирован, нажатие не делает ничего; при зажжённых экранах тот же бинд
срабатывает мгновенно). Значит клавишу надо читать напрямую из evdev, мимо
композитора.

ЗАЧЕМ ОТДЕЛЬНЫЙ ПОЛЬЗОВАТЕЛЬ. Чтобы читать /dev/input/event*, нужен доступ к
узлам клавиатур, а они лежат root:input. Выдать его самому себе (правилом с
uaccess) значит разрешить чтение всех нажатий любому процессу, запущенному от
твоего имени, — это полноценный кейлоггер для любой программы в сессии.
Поэтому доступ выдан ACL'ом отдельному системному пользователю screenwake, у
которого нет ни дома, ни шелла, ни чего-либо ещё, а сессия общается с ним
через сокет и получает один бит.

Отсюда же требование: файл демона лежит в /usr/local/lib и принадлежит root.
Если бы он лежал в домашней папке, любой процесс в сессии мог бы дописать в
него отправку всех нажатий — и вся изоляция потеряла бы смысл. Исходник в
~/.config/hypr/scripts/wake-on-space-daemon/ — это копия для правки, живой
демон обновляется только повторным запуском install.sh из-под root.

Устройства открываются только пока есть подключённый клиент, то есть пока
экраны погашены. В остальное время демон не читает клавиатуру вообще.

Протокол, построчно:
    клиент подключился        <- "armed"        (клавиатуры открыты, ждём)
                              <- "no-keyboards" (открыть нечего, соединение закрывается)
    нажали пробел             <- "space"        (и соединение закрывается)
"""

import os
import selectors
import socket
import sys

import evdev
from evdev import ecodes

SOCKET_PATH = "/run/wake-on-space/sock"


def keyboards():
    """Устройства, на которых есть и пробел, и буквы, — то есть клавиатуры.

    Два места, где evdev по умолчанию требует доступа на запись, а у нас его
    нет и быть не должно (писать в устройство ввода — это дёргать светодиоды и
    подсовывать события, демону такое ни к чему):

    writable=False у list_devices — иначе он молча отфильтрует всё, потому что
    проверяет os.access(R_OK|W_OK), и список выйдет пустым при совершенно
    исправном ACL на чтение. Ровно на этом всё и не заработало с первого раза.

    readonly=True у InputDevice — иначе он сначала пробует O_RDWR.
    """
    devs = []
    for path in sorted(evdev.list_devices(writable=False)):
        try:
            dev = evdev.InputDevice(path, readonly=True)
        except OSError as err:
            print(f"{path}: не открылся ({err})", file=sys.stderr, flush=True)
            continue
        keys = dev.capabilities().get(ecodes.EV_KEY, [])
        if ecodes.KEY_SPACE in keys and ecodes.KEY_A in keys:
            devs.append(dev)
        else:
            dev.close()
    if not devs:
        print("клавиатур не нашлось: проверь ACL "
              "(getfacl /dev/input/event* | grep screenwake)",
              file=sys.stderr, flush=True)
    else:
        print("слушаю: " + ", ".join(d.path for d in devs),
              file=sys.stderr, flush=True)
    return devs


class Daemon:
    def __init__(self):
        self.sel = selectors.DefaultSelector()
        self.clients = set()
        self.devices = []

    def arm(self):
        if self.devices:
            return True
        self.devices = keyboards()
        for dev in self.devices:
            self.sel.register(dev.fd, selectors.EVENT_READ, ("key", dev))
        return bool(self.devices)

    def disarm(self):
        for dev in self.devices:
            try:
                self.sel.unregister(dev.fd)
            except KeyError:
                pass
            dev.close()
        self.devices = []

    def say(self, conn, word):
        try:
            conn.sendall(word)
        except OSError:
            pass

    def drop(self, conn):
        self.clients.discard(conn)
        try:
            self.sel.unregister(conn)
        except KeyError:
            pass
        conn.close()
        if not self.clients:
            self.disarm()

    def forget_device(self, dev):
        """Клавиатура отвалилась — беспроводная ушла спать, USB выдернули."""
        try:
            self.sel.unregister(dev.fd)
        except KeyError:
            pass
        dev.close()
        self.devices = [d for d in self.devices if d is not dev]
        if not self.devices:
            # Будить больше нечем: честно говорим клиентам, чтобы зажигали.
            for conn in list(self.clients):
                self.say(conn, b"no-keyboards\n")
                self.drop(conn)

    def on_key(self, dev):
        try:
            events = list(dev.read())
        except OSError:
            self.forget_device(dev)
            return
        for ev in events:
            # value: 1 — нажатие, 2 — автоповтор, 0 — отпускание
            if ev.type == ecodes.EV_KEY and ev.code == ecodes.KEY_SPACE and ev.value == 1:
                for conn in list(self.clients):
                    self.say(conn, b"space\n")
                    self.drop(conn)
                return

    def run(self):
        if os.path.exists(SOCKET_PATH):
            os.unlink(SOCKET_PATH)
        srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        srv.bind(SOCKET_PATH)
        # Каталог создаёт systemd (RuntimeDirectory), он же задаёт группу; сокет
        # доступен этой группе, то есть только твоей сессии и root.
        os.chmod(SOCKET_PATH, 0o660)
        srv.listen(8)
        self.sel.register(srv, selectors.EVENT_READ, ("srv", None))

        while True:
            for key, _ in self.sel.select():
                kind, obj = key.data
                if kind == "srv":
                    conn, _ = srv.accept()
                    if not self.arm():
                        self.say(conn, b"no-keyboards\n")
                        conn.close()
                        continue
                    self.clients.add(conn)
                    self.sel.register(conn, selectors.EVENT_READ, ("client", conn))
                    self.say(conn, b"armed\n")
                elif kind == "client":
                    # Читать от клиента нечего: его единственное сообщение —
                    # это разрыв соединения (он погас и передумал ждать).
                    try:
                        alive = obj.recv(64)
                    except OSError:
                        alive = b""
                    if not alive:
                        self.drop(obj)
                else:
                    self.on_key(obj)


if __name__ == "__main__":
    sys.exit(Daemon().run())
