--!nonstrict
-- Счётчик разбора в баре. Сам ничего не считает и не запускает — читает то,
-- что положила служба, и зовёт её по IPC. Экземпляров столько, сколько баров.
--
--   левая клавиша    открыть панель
--   средняя          запустить разбор, не открывая панель
--   правая           пересчитать состояние прямо сейчас
--
-- Три состояния, три вида, и порядок между ними важен: «требует решения»
-- перебивает «есть новое», потому что новое разберётся само, а спорное и
-- помеченное так и будет лежать, пока на него не посмотрят.

local KEY = "ai_triage"
local PANEL = "q/ai-triage:triage"
local SERVICE = "q/ai-triage:watch"

local function poke(event)
  noctalia.runAsync("noctalia msg plugin " .. SERVICE .. " all " .. event)
end

local function refresh(s)
  s = s or {}
  local new = tonumber(s.new) or 0
  local decide = (tonumber(s.unsure) or 0) + (tonumber(s.warn) or 0)

  if s.running then
    barWidget.setGlyph("loader")
    barWidget.setText("")
    barWidget.setColor("primary")
    barWidget.setGlyphColor("primary")
  elseif decide > 0 then
    barWidget.setGlyph("alert-triangle")
    barWidget.setText(tostring(decide))
    barWidget.setColor("error")
    barWidget.setGlyphColor("error")
  elseif new > 0 then
    barWidget.setGlyph("checklist")
    barWidget.setText(tostring(new))
    barWidget.setColor("secondary")
    barWidget.setGlyphColor("secondary")
  else
    -- Разобрано всё. Виджет не прячется: он ещё и дверь в панель.
    barWidget.setGlyph("checklist")
    barWidget.setText("")
    barWidget.setColor("on_surface_variant")
    barWidget.setGlyphColor("on_surface_variant")
  end

  local rows = {}
  if s.running then
    table.insert(rows, { key = "идёт разбор", value = s.tail or "" })
  end
  table.insert(rows, { key = "не разобрано", value = tostring(new) })
  table.insert(rows, { key = "в индексе", value = tostring(tonumber(s.yes) or 0) })
  table.insert(rows, { key = "отсеяно", value = tostring(tonumber(s.no) or 0) })
  if (tonumber(s.unsure) or 0) > 0 then
    table.insert(rows, { key = "спорных", value = tostring(s.unsure) })
  end
  if (tonumber(s.warn) or 0) > 0 then
    table.insert(rows, { key = "небезопасных", value = tostring(s.warn) })
  end
  table.insert(rows, { key = "локальная модель", value = s.qwen and "на связи" or "спит" })
  barWidget.setTooltip(rows)
end

function onClick()
  noctalia.togglePanel(PANEL)
end

function onMiddleClick()
  poke("run")
end

function onRightClick()
  poke("refresh")
end

noctalia.state.watch(KEY, refresh)
refresh(noctalia.state.get(KEY))
