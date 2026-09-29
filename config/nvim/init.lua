-- Персональный конфиг nvim на lazy.nvim (уход с NvChad, 10.09.2026).
-- Портировано из NvChad-настройки: vue hybrid LSP, conform, nvim-ts-autotag,
-- matugen/base16-палитра. Новое: blink.cmp + minuet (AI-автодополнение), lua_ls/gopls, fzf-lua.
vim.g.mapleader = " "
vim.g.maplocalleader = " "

local lazypath = vim.fn.stdpath("data") .. "/lazy/lazy.nvim"
if not vim.uv.fs_stat(lazypath) then
  local repo = "https://github.com/folke/lazy.nvim.git"
  vim.fn.system({ "git", "clone", "--filter=blob:none", repo, "--branch=stable", lazypath })
end
vim.opt.rtp:prepend(lazypath)

require("lazy").setup({
  spec = {
    { import = "plugins" },
  },
}, require("config.lazy"))

require("config.options")
require("config.keymaps")
require("config.autocmds")

-- harness: маркер, что init.lua дошёл до конца; бенчмарк проверяет его
-- (headless nvim молчит при ошибке в init и всё равно выходит с кодом 0)
_G.__CFG_OK = true
