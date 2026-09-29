-- Базовые опции. Замена nvchad.options: только то, что реально хочется.
-- vim-провайдеры не нужны: LSP-серверы работают напрямую, а проверка
-- python3-хоста стоила ~23ms на каждом старте с открытым .py
vim.g.loaded_python3_provider = 0
vim.g.loaded_node_provider = 0
vim.g.loaded_ruby_provider = 0
vim.g.loaded_perl_provider = 0

local opt = vim.opt

-- строки и курсор
opt.number = true
opt.relativenumber = true
opt.signcolumn = "yes"
opt.cursorline = true
opt.scrolloff = 8
opt.sidescrolloff = 8

-- поиск
opt.ignorecase = true
opt.smartcase = true
opt.incsearch = true
opt.hlsearch = false

-- отступы: 2 по умолчанию, 4/табы — по filetype (см. autocmds)
opt.expandtab = true
opt.shiftwidth = 2
opt.tabstop = 2
opt.shiftround = true

-- файлы и история
opt.undofile = true
opt.swapfile = false
opt.updatetime = 250
opt.timeoutlen = 400

-- окна
opt.splitright = true
opt.splitbelow = true
opt.laststatus = 3
opt.showmode = false
opt.pumheight = 10
opt.cmdheight = 1
opt.completeopt = { "menu", "menuone", "noselect" }

-- терминал и мышь
opt.termguicolors = true
opt.mouse = "a"
opt.clipboard = "unnamedplus"

-- поиск по проекту
if vim.fn.executable("rg") == 1 then
  opt.grepprg = "rg --vimgrep"
  opt.grepformat = "%f:%l:%c:%m"
end

-- подсветка невидимых символов
opt.list = true
opt.listchars = { tab = "→ ", trail = "·", nbsp = "␣" }

-- статус-лайн без плагина (модуль config.statusline)
opt.statusline = "%!v:lua.require('config.statusline').render()"
