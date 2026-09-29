-- Worktree-менеджмент: fzf-lua git_worktrees поверх wt (worktrunk). Дефолтные
-- экшены пикера заменены: create/remove гоняются через wt, иначе ломаются его
-- layout ../.worktrees/<repo>/<branch> и хуки (дефолт ctrl-a кладёт в ../<branch>,
-- дефолт ctrl-x делает сырой git worktree remove мимо wt).
local function path_of(selected)
  return selected and selected[1] and selected[1]:match("^[^%s]+") or nil
end

-- Строка `git worktree list` — "<абсолютный путь> <sha> <ветка/пометка>".
-- Пикеру отдаём "<путь>\t<basename>\t<остаток>": fzf показывает только поля
-- 2 и 3 (--with-nth), поэтому визуально строка начинается с basename
-- worktree, а выбранная строка остаётся полной — путь по-прежнему первое
-- поле, его читают path_of, preview и wt-экшены. Непонятую строку вернём
-- как есть.
local function worktree_row(line)
  local path, rest = line:match("^(%S+)%s+(.*)$")
  if not path then
    return line
  end
  local name = vim.fs.basename(path)
  if name == "" then
    return line
  end
  return path .. "\t" .. name .. "\t" .. rest
end

-- cd в worktree + закрытие чужих буферов: только listed-файлы с абсолютным путём
-- и без правок — bufferline не смешивает два worktree; терминал/эксплорер/
-- модифицированные буферы не трогаем.
local function close_foreign_buffers(root)
  for _, buf in ipairs(vim.api.nvim_list_bufs()) do
    if vim.bo[buf].buflisted and vim.bo[buf].buftype == "" and not vim.bo[buf].modified then
      local name = vim.api.nvim_buf_get_name(buf)
      if name:sub(1, 1) == "/" and vim.fs.normalize(name):sub(1, #root + 1) ~= root .. "/" then
        pcall(vim.api.nvim_buf_delete, buf, {})
      end
    end
  end
end

local function worktree_enter(selected)
  local path = path_of(selected)
  if not path then return end
  local root = vim.fs.normalize(path)
  if root == vim.fs.normalize(vim.fn.getcwd()) then
    vim.notify("worktree: cwd already " .. root, vim.log.levels.INFO)
    return
  end
  close_foreign_buffers(root)
  vim.cmd({ cmd = "cd", args = { root } })
  vim.notify("worktree: " .. root, vim.log.levels.INFO)
end

-- ctrl-a: имя ветки берётся из промпта пикера (field_index = "{q}")
local function worktree_add(selected, o)
  local q = selected[1] or ""
  if q == "" and o and o.last_query then q = o.last_query end
  local branch = vim.trim(q)
  if branch == "" then
    vim.notify("worktree: type branch name in the prompt", vim.log.levels.WARN)
    return
  end
  vim.fn.system({ "wt", "switch", "--create", branch })
  if vim.v.shell_error ~= 0 then
    vim.notify("wt switch --create " .. branch .. " failed", vim.log.levels.ERROR)
    return
  end
  -- где wt поселил ветку — спрашиваем у git, не дублируем шаблон пути wt
  local out = vim.fn.system({ "git", "worktree", "list", "--porcelain" })
  local wt_path
  for line in vim.gsplit(out, "\n") do
    local p = line:match("^worktree%s+(.+)$")
    if p then wt_path = p end
    if line == "branch refs/heads/" .. branch then
      return worktree_enter({ wt_path })
    end
  end
  vim.notify("worktree created, but branch " .. branch .. " not found", vim.log.levels.WARN)
end

local function worktree_del(selected)
  local path = path_of(selected)
  if not path then return end
  if vim.fs.normalize(path) == vim.fs.normalize(vim.fn.getcwd()) then
    vim.notify("worktree: cannot remove the current one", vim.log.levels.WARN)
    return
  end
  if vim.fn.confirm("Remove worktree " .. path .. "?", "&Yes\n&No") ~= 1 then
    return
  end
  vim.fn.system({ "wt", "remove", "--foreground", path })
  if vim.v.shell_error ~= 0 then
    vim.notify("wt remove failed (dirty tree? see wt remove -f)", vim.log.levels.ERROR)
  else
    vim.notify("worktree removed: " .. path, vim.log.levels.INFO)
  end
end

return {
  {
    "ibhagwan/fzf-lua",
    dependencies = { "nvim-tree/nvim-web-devicons" },
    cmd = "FzfLua",
    keys = {
      { "<leader>ff", "<cmd>FzfLua files<cr>", desc = "find files" },
      { "<leader>fg", "<cmd>FzfLua live_grep<cr>", desc = "live grep" },
      { "<leader>fb", "<cmd>FzfLua buffers<cr>", desc = "buffers" },
      { "<leader>fh", "<cmd>FzfLua helptags<cr>", desc = "help tags" },
      { "<leader>fw", "<cmd>FzfLua git_worktrees<cr>", desc = "worktrees (wt)" },
    },
    opts = {
      git = {
        worktrees = {
          fn_transform = worktree_row,
          -- показываем поля 2,3 (basename + sha/ветка), поле 1 (путь) скрыто,
          -- но остаётся первым в выбранной строке
          fzf_opts = {
            ["--delimiter"] = "\t",
            ["--with-nth"] = "2,3",
          },
          -- enter — cd + чистка чужих буферов; ctrl-a/ctrl-x — create/remove через wt
          actions = {
            ["enter"] = worktree_enter,
            ["ctrl-a"] = { fn = worktree_add, field_index = "{q}", reload = true },
            ["ctrl-x"] = { fn = worktree_del, reload = true },
          },
        },
      },
    },
  },
}
