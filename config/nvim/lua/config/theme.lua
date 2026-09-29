-- Тема: base16 поверх статичной палитры (config/palette.lua). Портировано
-- из NvChad-конфига; палитра фиксирована и правится вручную — Noctalia её
-- больше не генерирует.
local M = {}

function M.setup()
  local p = require("config.palette")

  require("base16-colorscheme").setup({
    base00 = p.bg,
    base01 = p.bg2,
    base02 = p.sel,
    base03 = p.muted,
    base04 = p.fg_dim,
    base05 = p.fg,
    base06 = p.fg,
    base07 = p.fg,
    base08 = p.red,
    base09 = p.violet,
    base0A = p.fg_dim,
    base0B = p.accent,
    base0C = p.violet,
    base0D = p.accent,
    base0E = p.fg_dim,
    base0F = p.fg,
  })

  -- плавающие окна (fzf-lua, документация blink) под ту же палитру
  local hi = vim.api.nvim_set_hl
  hi(0, "NormalFloat", { fg = p.fg, bg = p.bg })
  hi(0, "FloatBorder", { fg = p.muted, bg = p.bg })
  hi(0, "Pmenu", { fg = p.fg, bg = p.bg2 })
  hi(0, "PmenuSel", { fg = p.bg, bg = p.accent, bold = true })
  hi(0, "PmenuSbar", { bg = p.bg2 })
  hi(0, "PmenuThumb", { bg = p.sel })
  hi(0, "CursorLine", { bg = p.bg2 })
end

return M
