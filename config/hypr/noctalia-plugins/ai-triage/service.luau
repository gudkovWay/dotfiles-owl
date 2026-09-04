--!nonstrict
-- Служба разбора: единственный, кто считает состояние и гоняет обход.
--
-- Почему служба, а не сам виджет: экземпляр виджета живёт на каждом баре, то
-- есть на каждом мониторе, и опрос из него шёл бы втрое чаще без всякой
-- пользы. Плюс обход идёт минутами — он не должен обрываться от того, что
-- панель закрыли.
--
-- Виджет и панель только читают `noctalia.state`; менять его отсюда — правило,
-- а не совпадение: два писателя в одно состояние разошлись бы при первой же
-- гонке между опросом и прогоном.
--
-- Команды приходят по IPC:
--   noctalia msg plugin q/ai-triage:watch all run|guard|escalate|index
--   noctalia msg plugin q/ai-triage:watch all refresh|clear

local KEY = "ai_triage"
local AI = "/home/q/storage/ai"
local POLL_MS = 60000
local MAX_LINES = 200       -- строк лога держим ровно столько, сколько влезет
                            -- в панель прокруткой; остальное — в терминал

local data = {
  new = 0, unsure = 0, warn = 0, yes = 0, no = 0, unread = 0, total = 0,
  qwen = false, running = false, lines = {}, tail = "", at = 0,
}

-- Сводку показываем один раз на прогон, а не на каждый опрос.
local announce = false

local function publish()
  data.at = os.time()
  noctalia.state.set(KEY, data)
end

-- В выводе triage.py есть цвета терминала: «⚠» приезжает обёрнутым в \27[31m.
-- В панели своя разметка, escape-последовательности там — мусор.
local function plain(line)
  return (string.gsub(line, "\27%[[0-9;]*m", ""))
end

-- Уведомляем через notify-send, а не через noctalia.notify. Разница не в
-- красоте: свои уведомления Noctalia помечает origin=internal и в
-- `~/.local/state/noctalia/notification_history.json` не кладёт вовсе —
-- всплыло, погасло, найти нечем. Через notify-send оно приходит как внешнее
-- и остаётся в истории. На том же месте уже обжигались с `urgency=low`,
-- который туда тоже не попадает.
local function quoted(s)
  return "'" .. string.gsub(s, "'", "'\\''") .. "'"
end

local function notify(urgency, timeoutMs, title, body)
  noctalia.runAsync(string.format("notify-send -a ai -u %s -t %d %s %s",
    urgency, timeoutMs, quoted(title), quoted(body)))
end

local function summary()
  return string.format("в индексе %d · отсеяно %d · спорных %d · небезопасных %d",
    data.yes, data.no, data.unsure, data.warn)
end

local function poll()
  noctalia.runAsync(AI .. "/bin/triage.py state", function(res)
    if not res or res.exitCode ~= 0 then
      return
    end
    local got = noctalia.json.decode(res.stdout or "")
    if type(got) ~= "table" then
      return
    end
    for _, k in ipairs({ "new", "unsure", "warn", "yes", "no", "unread", "total" }) do
      data[k] = tonumber(got[k]) or 0
    end
    data.qwen = got.qwen == true
    -- Замок общий: обход, запущенный из терминала, виден в баре так же.
    data.running = got.running == true
    if announce and not data.running then
      announce = false
      notify("normal", 8000, "Разбор закончен", summary())
    end
    publish()
  end, 20000)
end

-- Поток строк: у runStream нет onClose, поэтому конец потока распознаётся по
-- последней строке самого скрипта. pass.sh обязан её напечатать в любом
-- исходе — и в нормальном, и через trap.
local function terminal(line)
  return string.match(line, "^готово")
      or string.match(line, "^прервано")
      or string.match(line, "^занято")
end

local function start(cmd, label)
  if data.running then
    return
  end
  data.running = true
  data.lines = { label }
  data.tail = label
  publish()

  local ok = noctalia.runStream(cmd, function(raw)
    local line = noctalia.string.trim(plain(raw))
    if line == "" then
      return
    end
    table.insert(data.lines, line)
    if #data.lines > MAX_LINES then
      table.remove(data.lines, 1)
    end
    data.tail = line
    if terminal(line) then
      data.running = false
      announce = not string.match(line, "^занято")
      poll()                      -- счётчики берём с диска, а не из строки
    end
    publish()
  end)

  if not ok then
    data.running = false
    data.tail = "не удалось запустить: " .. cmd
    notify("critical", 0, "Разбор не запустился", cmd)
    publish()
  end
end

function update()
  poll()
end

function onIpc(event, payload)
  if event == "run" then
    start(AI .. "/bin/pass.sh", "запускаю разбор…")
  elseif event == "guard" then
    start(AI .. "/bin/pass.sh guard", "охранный проход…")
  elseif event == "escalate" then
    start(AI .. "/bin/pass.sh escalate", "спорные — Claude…")
  elseif event == "index" then
    start(AI .. "/bin/pass.sh index", "пересобираю индекс…")
  elseif event == "refresh" then
    poll()
  elseif event == "clear" then
    data.lines = {}
    data.tail = ""
    publish()
  end
end

noctalia.setUpdateInterval(POLL_MS)
publish()
poll()
