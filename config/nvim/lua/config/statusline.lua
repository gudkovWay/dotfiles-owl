-- Статус-лайн без плагинов: режим | ветка+диагностика | файл | LSP | позиция.
-- Палитра — статичная, из config/palette.lua (правится вручную, Noctalia её
-- больше не генерирует).
-- Группы строятся заново по M.reload(), чтобы смена палитры применялась
-- без перезапуска nvim.
local M = {}

local modes

local function build()
  local p = require("config.palette")

  -- key → { подпись, фон плашки режима }
  local defs = {
    n = { "NORMAL", p.accent },
    i = { "INSERT", p.fg_dim },
    v = { "VISUAL", p.violet },
    V = { "V-LINE", p.violet },
    ["\22"] = { "V-BLOCK", p.violet },
    c = { "COMMAND", p.fg_dim },
    R = { "REPLACE", p.red },
    t = { "TERM", p.muted },
  }

  modes = {}
  for key, def in pairs(defs) do
    local group = "UserStMode" .. key:gsub("%W", "Block")
    vim.api.nvim_set_hl(0, group, { fg = p.bg, bg = def[2], bold = true })
    modes[key] = { label = def[1], group = group }
  end

  -- сегменты гита/диагностики под палитру
  vim.api.nvim_set_hl(0, "UserStBranch", { fg = p.accent, bg = p.bg2, bold = true })
  vim.api.nvim_set_hl(0, "UserStErr", { fg = p.red, bg = p.bg2 })
  vim.api.nvim_set_hl(0, "UserStWarn", { fg = p.fg_dim, bg = p.bg2 })
end

function M.reload()
  build()
end

build()

-- Экранирует литеральные % во внешних подписях (имя ветки gitsigns, имя
-- LSP-клиента), чтобы их содержимое не стало директивой статус-лайна.
local function escape_label(label)
  return (label:gsub("%%", "%%%%"))
end

function M.render()
  local mode = modes[vim.api.nvim_get_mode().mode] or modes.n
  local p = "%#StatusLine#"

  -- ветка (gitsigns кладёт её в buffer-local переменную) и диагностика
  local git = ""
  local branch = vim.b.gitsigns_head
  if branch then
    git = "%#UserStBranch#  " .. escape_label(branch) .. " "
  end
  local errs = #vim.diagnostic.get(0, { severity = vim.diagnostic.severity.ERROR })
  local warns = #vim.diagnostic.get(0, { severity = vim.diagnostic.severity.WARN })
  if errs + warns > 0 then
    git = git .. "%#UserStErr#" .. errs .. " %#UserStWarn#" .. warns .. " "
  end

  local lsp = ""
  local clients = vim.lsp.get_clients({ bufnr = 0 })
  if #clients > 0 then
    lsp = "  %#Comment#" .. escape_label(clients[1].name)
  end

  -- файл: штатный %f (экранный путь рисует сам vim)
  return table.concat({
    "%#", mode.group, "# ", mode.label,
    " ", git, p, " %f %m%r",
    "%=", lsp, p, " %l:%c ",
  })
end

return M
