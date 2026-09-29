-- Автокоманды.
local aug = vim.api.nvim_create_augroup("user", { clear = true })

-- подсветка при yank
vim.api.nvim_create_autocmd("TextYankPost", {
  group = aug,
  callback = function() vim.hl.on_yank() end,
})

-- treesitter-подсветка нативно: main-ветка nvim-treesitter переписала
-- конфиг-модуль, opts.highlight теряется — attach сам по FileType;
-- для filetype без парсера тихо остаётся regex-синтаксис
vim.api.nvim_create_autocmd("FileType", {
  group = aug,
  callback = function(args)
    if pcall(vim.treesitter.start, args.buf) then
      vim.bo[args.buf].syntax = ""
    end
  end,
})

-- возврат курсора на последнюю позицию в файле
vim.api.nvim_create_autocmd("BufReadPost", {
  group = aug,
  callback = function()
    local mark = vim.api.nvim_buf_get_mark(0, '"')
    if mark[1] > 0 and mark[1] <= vim.api.nvim_buf_line_count(0) then
      vim.api.nvim_win_set_cursor(0, mark)
    end
  end,
})

-- не комментировать автоматически строки при o/O/Enter
vim.api.nvim_create_autocmd("FileType", {
  group = aug,
  callback = function()
    vim.opt_local.formatoptions:remove({ "r", "o" })
  end,
})

-- отступы по filetype: python — 4, go — табы 4
vim.api.nvim_create_autocmd("FileType", {
  group = aug,
  pattern = { "python" },
  callback = function()
    vim.opt_local.shiftwidth = 4
    vim.opt_local.tabstop = 4
  end,
})
vim.api.nvim_create_autocmd("FileType", {
  group = aug,
  pattern = { "go" },
  callback = function()
    vim.opt_local.shiftwidth = 4
    vim.opt_local.tabstop = 4
    vim.opt_local.expandtab = false
  end,
})

-- Непрозрачный фон под nvim (как в Zed): kitty по умолчанию полупрозрачный
-- (background_opacity 0.6), под редактором поднимаем фон СВОЕГО окна kitty до
-- 0.9 — обои чуть просвечивают, но текст читаемый; на выходе/паузе возвращаем
-- 0.6, чтобы шелл остался прежним. Работает только в своём окне (--to сокет из
-- KITTY_LISTEN_ON); нужен `dynamic_background_opacity yes` в kitty.conf.
local kitty_sock = os.getenv("KITTY_LISTEN_ON")
if kitty_sock and kitty_sock ~= "" then
  local function kopacity(v)
    vim.fn.system({ "kitty", "@", "--to", kitty_sock, "set-background-opacity", v })
  end
  vim.api.nvim_create_autocmd({ "VimEnter", "VimResume" }, {
    group = aug,
    callback = function() kopacity("0.9") end,
  })
  vim.api.nvim_create_autocmd({ "VimLeavePre", "VimSuspend" }, {
    group = aug,
    callback = function() kopacity("0.6") end,
  })
end
