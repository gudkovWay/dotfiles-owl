--!nonstrict
-- Панель разбора: список карточек с вердиктами, запуск обхода и решения по
-- тому, что модель сочла небезопасным.
--
-- Данные приходят из двух мест, и это не лень, а разделение:
--   · счётчики, ход обхода и его лог — из noctalia.state, их пишет служба;
--   · сам список — своим вызовом `triage.py rows --json` при открытии и
--     после каждого действия. Список нужен только пока панель открыта,
--     гонять его в фоне раз в минуту не за чем.
--
-- Вердикт модели — черновик. Поэтому «класть/не класть» стоит одно нажатие,
-- а чтобы решать было по чему, строка разворачивается в начало карточки:
-- ровно то, что в fzf показывал bat в соседнем окне.

local KEY = "ai_triage"
local AI = "/home/q/storage/ai"
local SERVICE = "q/ai-triage:watch"

local PREVIEW_LINES = 28    -- сколько строк карточки показывать в развороте
local LOG_HEIGHT = 116

local rows = {}             -- всё, что вернул triage.py rows --json
local st = {}               -- то, что положила служба
local filter = "new"
local expanded = nil        -- путь развёрнутой карточки
local preview = {}          -- её начало, уже разбитое на строки
local confirm = nil         -- какая опасная кнопка ждёт второго нажатия
local busy = false          -- идёт действие: кнопки гасим, чтобы не задвоить
local opened = false

-- Путь уезжает в /bin/sh, а в именах карточек живут заголовки разговоров.
local function quoted(s)
  return "'" .. string.gsub(s, "'", "'\\''") .. "'"
end

local function poke(event)
  noctalia.runAsync("noctalia msg plugin " .. SERVICE .. " all " .. event)
end

local function count(pred)
  local n = 0
  for _, r in ipairs(rows) do
    if pred(r) then
      n += 1
    end
  end
  return n
end

-- «Новое» тут — то, чего не видел разбор, а не то, чего не видел ты: с ним
-- работает кнопка «Разобрать», и счётчик под ней должен совпадать с её
-- числом. Непрочитанное — другая ось, у него свой знак ● в строке.
--
-- Спорное — только то, что модель посмотрела и не решила. У неразобранной
-- карточки в заголовке тоже стоит `index: ?`, но это «ещё не спрашивали»,
-- и валить их в одну кучу значит показывать 38 спорных там, где их ноль.
local MATCH = {
  new = function(r) return r.fresh end,
  all = function() return true end,
  unsure = function(r) return r.verdict == "?" and not r.fresh end,
  warn = function(r) return r.share == "warning" end,
}

local render  -- вперёд: обработчики зовут его раньше, чем он определён

local function reload()
  noctalia.runAsync(AI .. "/bin/triage.py rows --json", function(res)
    busy = false
    if res and res.exitCode == 0 then
      local got = noctalia.json.decode(res.stdout or "")
      if type(got) == "table" then
        rows = got
        -- Первый заход открывает панель на новом; если нового нет, показывать
        -- пустой список глупо — падаем на «все».
        if filter == "new" and count(MATCH.new) == 0 then
          filter = "all"
        end
      end
    end
    render()
  end, 20000)
end

-- Любое действие меняет и список, и счётчики в баре: перечитываем оба.
local function act(cmd)
  if busy then
    return
  end
  busy = true
  confirm = nil
  render()
  noctalia.runAsync(cmd, function()
    poke("refresh")
    reload()
  end, 30000)
end

local function flip(path, verdict)
  act(AI .. "/bin/triage.py flip " .. quoted(path) .. " --verdict " .. verdict)
end

local function allow(path, value)
  act(AI .. "/bin/triage.py allow " .. quoted(path) .. " " .. value)
end

-- Заголовок карточки нам уже показан в строке; в развороте нужен разговор.
local function loadPreview(path)
  preview = {}
  local text = noctalia.readFile(path)
  if not text then
    preview = { "карточка не читается" }
    return
  end
  local body = string.match(text, "^%-%-%-.-\n%-%-%-\n(.*)$") or text
  for line in string.gmatch(body, "[^\n]*") do
    if #preview >= PREVIEW_LINES then
      table.insert(preview, "…")
      break
    end
    if noctalia.string.trim(line) ~= "" then
      table.insert(preview, line)
    end
  end
end

local function toggle(path)
  if expanded == path then
    expanded, preview = nil, {}
  else
    expanded = path
    loadPreview(path)
  end
  render()
end


-- ─────────────────────────────────────────────────────────── куски разметки

local MARK = {
  ["да"] = { "+", "primary" },
  ["нет"] = { "−", "error" },
  ["?"] = { "?", "tertiary" },
}

-- Неразобранная карточка — не «спорная»: точка, а не вопрос.
local function markOf(r)
  if r.fresh then
    return { "·", "on_surface_variant" }
  end
  return MARK[r.verdict] or MARK["?"]
end

-- «2026-09-04 14:00» читается как дата в базе, а не как строка в списке.
local function shortDate(s)
  local d, m, hm = string.match(s or "", "^%d+%-(%d+)%-(%d+) (%d+:%d+)")
  if d then
    return m .. "." .. d .. " " .. hm
  end
  return s or ""
end

local function chip(id, text, n)
  return ui.button({
    key = "f" .. id,
    text = n > 0 and (text .. " " .. n) or text,
    controlSize = "sm",
    variant = filter == id and "primary" or "ghost",
    onClick = function()
      filter = id
      render()
    end,
  })
end

local function header()
  local qwen = st.qwen and "модель на связи" or "модель спит"
  return ui.row({ key = "head", gap = 8, align = "center" }, {
    ui.glyph({ name = "checklist", size = 20, color = "primary" }),
    ui.label({ text = "Разбор сессий", fontSize = 15, fontWeight = "semibold" }),
    ui.spacer({ flexGrow = 1 }),
    ui.label({
      text = string.format("в индексе %d · отсеяно %d · %s",
        tonumber(st.yes) or 0, tonumber(st.no) or 0, qwen),
      fontSize = 12,
      color = "on_surface_variant",
    }),
    ui.button({
      key = "reload",
      glyph = "refresh",
      controlSize = "sm",
      variant = "ghost",
      tooltip = "пересчитать",
      enabled = not busy,
      onClick = function()
        poke("refresh")
        reload()
      end,
    }),
  })
end

local function actions()
  local new = tonumber(st.new) or 0
  local unsure = tonumber(st.unsure) or 0
  local running = st.running == true
  local items = {}

  table.insert(items, ui.button({
    key = "run",
    text = running and "идёт разбор…"
        or (new > 0 and ("Разобрать " .. new .. " новых") or "Прогнать заново"),
    glyph = running and "loader" or "player-play",
    variant = new > 0 and "primary" or "outline",
    controlSize = "sm",
    enabled = not running and not busy,
    tooltip = "пересборка → охрана → вердикты → индекс",
    onClick = function()
      poke("run")
    end,
  }))

  if unsure > 0 then
    -- Единственная кнопка, которая тратит деньги, — поэтому в два нажатия.
    table.insert(items, ui.button({
      key = "esc",
      text = confirm == "escalate" and "точно? платно"
          or ("Спорные → Claude (" .. unsure .. ")"),
      glyph = "cloud-upload",
      variant = confirm == "escalate" and "destructive" or "outline",
      controlSize = "sm",
      enabled = not running and not busy,
      onClick = function()
        if confirm == "escalate" then
          confirm = nil
          poke("escalate")
        else
          confirm = "escalate"
        end
        render()
      end,
    }))
  end

  table.insert(items, ui.button({
    key = "guard",
    glyph = "shield",
    text = "Охрана",
    variant = "ghost",
    controlSize = "sm",
    enabled = not running and not busy,
    tooltip = "перебрать ввозные карточки локальной моделью",
    onClick = function()
      poke("guard")
    end,
  }))

  table.insert(items, ui.spacer({ flexGrow = 1 }))
  table.insert(items, ui.button({
    key = "term",
    glyph = "terminal-2",
    variant = "ghost",
    controlSize = "sm",
    tooltip = "то же в терминале: ai triage review",
    onClick = function()
      noctalia.runInTerminal(AI .. "/bin/ai triage review")
      panel.close()
    end,
  }))

  return ui.row({ key = "act", gap = 6, align = "center" }, items)
end

local function log()
  local lines = st.lines or {}
  if #lines == 0 then
    return nil
  end
  local items = {}
  for i, line in ipairs(lines) do
    local color = "on_surface_variant"
    local head = string.sub(line, 1, 1)
    if head == "+" then
      color = "primary"
    elseif head == "−" then
      color = "error"
    elseif head == "⚠" or head == "?" then
      color = "tertiary"
    elseif string.match(line, "^готово") then
      color = "primary"
    end
    table.insert(items, ui.label({
      key = "l" .. i,
      text = line,
      fontSize = 11,
      maxLines = 1,
      color = color,
    }))
  end
  return ui.scroll({
    key = "log",
    height = LOG_HEIGHT,
    gap = 1,
    padding = 8,
    radius = 8,
    fill = "surface_variant/0.6",
    stickToBottom = true,
  }, items)
end

local function card(r, i)
  local mark = markOf(r)
  local warned = r.share == "warning"
  local open = expanded == r.path

  local head = ui.row({
    key = "h" .. i,
    gap = 8,
    align = "center",
    paddingH = 6,
    paddingV = 3,
    onClick = function()
      toggle(r.path)
    end,
  }, {
    ui.label({ text = r.unread and "●" or " ", fontSize = 11, color = "secondary", width = 10 }),
    ui.label({ text = warned and "⚠" or mark[1], fontSize = 13,
               color = warned and "error" or mark[2], width = 12 }),
    ui.label({ text = shortDate(r.date), fontSize = 11,
               color = "on_surface_variant", width = 74 }),
    ui.label({ text = r.title, fontSize = 12, maxLines = 1, flexGrow = 1 }),
    ui.label({ text = warned and r.share_why or r.why, fontSize = 11, maxLines = 1,
               maxWidth = 200, color = "on_surface_variant" }),
    ui.label({ text = r.model, fontSize = 10, color = "on_surface_variant", width = 52 }),
    ui.button({ key = "y" .. i, glyph = "check", controlSize = "sm",
                variant = r.verdict == "да" and "primary" or "ghost",
                tooltip = "класть в индекс", enabled = not busy,
                onClick = function() flip(r.path, "да") end }),
    ui.button({ key = "n" .. i, glyph = "x", controlSize = "sm",
                variant = r.verdict == "нет" and "destructive" or "ghost",
                tooltip = "не класть", enabled = not busy,
                onClick = function() flip(r.path, "нет") end }),
  })

  if not open then
    return ui.column({ key = "c" .. i, radius = 8 }, { head })
  end

  local body = {}
  for j, line in ipairs(preview) do
    table.insert(body, ui.label({
      key = "p" .. i .. "_" .. j,
      text = line,
      fontSize = 11,
      maxLines = 1,
      color = "on_surface_variant",
    }))
  end

  local tools = { ui.button({
    key = "open" .. i,
    glyph = "edit",
    text = "открыть целиком",
    controlSize = "sm",
    variant = "ghost",
    onClick = function()
      noctalia.runInTerminal("nvim " .. quoted(r.path))
      panel.close()
    end,
  }) }

  if warned then
    -- Метку ставит модель, снимает человек: пока не снял, эскалация к Claude
    -- эту карточку не берёт.
    table.insert(tools, ui.button({
      key = "ok" .. i, glyph = "shield-check", text = "можно наружу",
      controlSize = "sm", variant = "outline", enabled = not busy,
      onClick = function() allow(r.path, "approved") end,
    }))
    table.insert(tools, ui.button({
      key = "never" .. i, glyph = "shield-x", text = "никогда",
      controlSize = "sm", variant = "ghost", enabled = not busy,
      onClick = function() allow(r.path, "never") end,
    }))
  end
  table.insert(tools, ui.spacer({ flexGrow = 1 }))

  return ui.column({
    key = "c" .. i,
    radius = 8,
    fill = "surface_variant/0.5",
    paddingV = 4,
    gap = 4,
  }, {
    head,
    ui.column({ key = "b" .. i, gap = 1, paddingH = 14 }, body),
    ui.row({ key = "t" .. i, gap = 6, paddingH = 10, paddingV = 2 }, tools),
  })
end

local function list()
  local match = MATCH[filter] or MATCH.all
  local items = {}
  for i, r in ipairs(rows) do
    if match(r) then
      table.insert(items, card(r, i))
    end
  end
  if #items == 0 then
    return ui.column({ key = "empty", align = "center", justify = "center",
                       flexGrow = 1, gap = 8 }, {
      ui.glyph({ name = "check", size = 30, color = "on_surface_variant" }),
      ui.label({ text = "тут пусто", color = "on_surface_variant" }),
    })
  end
  return ui.scroll({ key = "list", flexGrow = 1, gap = 2 }, items)
end


render = function()
  if not opened then
    return
  end
  local body = {
    header(),
    actions(),
  }
  local logged = log()
  if logged then
    table.insert(body, logged)
  end
  table.insert(body, ui.row({ key = "filters", gap = 6, align = "center" }, {
    chip("new", "новые", count(MATCH.new)),
    chip("all", "все", #rows),
    chip("unsure", "спорные", count(MATCH.unsure)),
    chip("warn", "⚠", count(MATCH.warn)),
  }))
  table.insert(body, list())

  panel.render(ui.column({
    padding = 14,
    gap = 8,
    flexGrow = 1,
  }, body))
end


function onOpen()
  opened = true
  busy = false
  confirm = nil
  expanded, preview = nil, {}
  st = noctalia.state.get(KEY) or {}
  render()
  reload()
end

function onClose()
  opened = false
  rows = {}
  expanded, preview = nil, {}
end

-- Служба пишет состояние и во время обхода: лог в панели едет сам собой.
noctalia.state.watch(KEY, function(value)
  st = value or {}
  render()
end)
