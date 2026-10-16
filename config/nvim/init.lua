-- Персональный конфиг nvim на lazy.nvim (уход с NvChad, 10.09.2026).
-- Портировано из NvChad-настройки: vue hybrid LSP, conform, nvim-ts-autotag,
-- matugen/base16-палитра. Новое: blink.cmp + minuet (AI-автодополнение), lua_ls/gopls, fzf-lua.
-- Не исполнять настройки из открываемых файлов и локальных конфигов проектов.
vim.o.modeline = false
vim.o.exrc = false

-- Не искать Lua-модули в cwd: необязательный require не должен запускать код проекта.
local function without_cwd(paths)
  local trusted = {}
  for path in paths:gmatch("[^;]+") do
    if path ~= "./?.lua" and path ~= "./?/init.lua" and path ~= "./?.so" then
      trusted[#trusted + 1] = path
    end
  end
  return table.concat(trusted, ";")
end
package.path = without_cwd(package.path)
package.cpath = without_cwd(package.cpath)

vim.g.mapleader = " "
vim.g.maplocalleader = " "

local lazypath = vim.fn.stdpath("data") .. "/lazy/lazy.nvim"
if not vim.uv.fs_stat(lazypath) then
  local repo = "https://github.com/folke/lazy.nvim.git"
  vim.fn.system({ "git", "clone", "--filter=blob:none", repo, "--branch=stable", lazypath })
end
vim.opt.rtp:prepend(lazypath)

require("lazy").setup({
  local_spec = false, -- .lazy.lua из cwd не должен выполняться независимо от 'exrc'.
  spec = {
    { import = "plugins" },
  },
}, require("config.lazy"))

require("config.options")
require("config.keymaps")
require("config.autocmds")
require("config.autoreload").setup()

-- harness: маркер, что init.lua дошёл до конца; бенчмарк проверяет его
-- (headless nvim молчит при ошибке в init и всё равно выходит с кодом 0)
_G.__CFG_OK = true
