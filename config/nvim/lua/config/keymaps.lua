-- Клавиши. Из NvChad-конфига взято привычное (; и jk), остальное — базовый
-- джентльменский набор; tmux-навигация C-h/j/k/l — vim-tmux-navigator
-- (plugins/tmux.lua): у края сплита клавиша уходит в панель tmux.
local map = vim.keymap.set

-- привычное из NvChad: ; — командный режим; escape — jk/jj (+ ол/оо на русской)
map("n", ";", ":", { desc = "command mode" })
for _, keys in ipairs({ "jk", "jj", "ол", "оо" }) do
  map("i", keys, "<ESC>", { desc = "escape" })
end

-- окна: см. plugins/tmux.lua (vim-tmux-navigator)

-- C-s сохраняет в любом режиме; из insert не выкидывает (<cmd>)
map({ "n", "i", "v" }, "<C-s>", "<cmd>w<cr>", { desc = "save" })
map("n", "<leader>/", "<cmd>FzfLua live_grep<cr>", { desc = "grep (по словам)" })

-- буферы-вкладки (bufferline): Tab/Shift-Tab циклом, Ctrl-<цифра> — по номеру
-- вкладки (номера видны на bufferline: numbers=ordinal). Tab≠C-i: kitty-протокол
-- клавиатуры их различает, прыжок по jumplist <C-i> цел.
map("n", "<Tab>", "<cmd>BufferLineCycleNext<cr>", { desc = "next buffer" })
map("n", "<S-Tab>", "<cmd>BufferLineCyclePrev<cr>", { desc = "prev buffer" })
for i = 1, 9 do
  map("n", ("<C-%d>"):format(i),
      ("<cmd>BufferLineGoToBuffer %d<cr>"):format(i),
      { desc = ("go to buffer %d"):format(i) })
end
-- [b / ]b — нативные prev/next; закрытие буфера/остальных
map("n", "<leader>bd", "<cmd>bdelete<cr>", { desc = "delete buffer" })
map("n", "<leader>bo", "<cmd>%bdelete|edit#|bdelete#<cr>", { desc = "close others" })
-- короткие алиасы: w — закрыть текущий буфер (файл), q — закрыть остальные
map("n", "<leader>w", "<cmd>bdelete<cr>", { desc = "close buffer" })
map("n", "<leader>q", "<cmd>%bdelete|edit#|bdelete#<cr>", { desc = "close other buffers" })

-- поиск и правка
map("n", "<esc>", "<cmd>nohlsearch<cr>", { desc = "clear search" })
map("v", "J", ":m '>+1<cr>gv=gv", { desc = "move line down", silent = true })
map("v", "K", ":m '<-2<cr>gv=gv", { desc = "move line up", silent = true })
map("n", "n", "nzzzv", { desc = "next match centered" })
map("n", "N", "Nzzzv", { desc = "prev match centered" })
map("n", "Y", "y$", { desc = "yank to eol" })

-- терминал
map("t", "<esc><esc>", [[<C-\><C-n>]], { desc = "terminal normal mode" })
