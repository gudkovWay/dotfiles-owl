-- Native reload decisions protect unsaved edits; directory watches survive atomic writes.
local M = {}
local api, uv = vim.api, vim.uv
local ns = api.nvim_create_namespace("user_external_changes")
local dirs, buffers, pending, before = {}, {}, {}, {}
local active, checking, group, original_autoread = false, false, nil, nil

local function close(handle)
  if handle and not handle:is_closing() then
    handle:stop()
    handle:close()
  end
end

local function detach(buf)
  local state = buffers[buf]
  pending[buf], before[buf] = nil, nil
  if not state then return end
  buffers[buf] = nil
  close(state.expiry)
  if api.nvim_buf_is_valid(buf) then
    vim.bo[buf].autoread = state.autoread
    api.nvim_buf_clear_namespace(buf, ns, 0, -1)
  end
  local dir = dirs[state.dir]
  if not dir then return end
  dir.buffers[buf] = nil
  if not next(dir.buffers) then
    dirs[state.dir] = nil
    close(dir.timer)
    close(dir.watcher)
  end
end

local highlight
local function reread(buf)
  if vim.bo[buf].modified and vim.fn.confirm(
    "Файл изменён снаружи. Перечитать и отбросить несохранённые правки?",
    "&Перечитать\n&Оставить", 2
  ) ~= 1 then return end
  local old = api.nvim_buf_get_lines(buf, 0, -1, false)
  local ok, err = pcall(api.nvim_buf_call, buf, function()
    local view = vim.fn.winsaveview()
    vim.cmd({ cmd = "edit", bang = true, mods = { silent = true, keepalt = true, keepjumps = true } })
    vim.fn.winrestview(view)
  end)
  if ok then highlight(buf, old) else vim.notify("reload: " .. err, vim.log.levels.WARN) end
end

local function flush()
  if not active or checking or api.nvim_get_mode().mode ~= "n" or vim.fn.getcmdwintype() ~= "" then return end
  checking = true
  for buf, from_fs in pairs(pending) do
    pending[buf] = nil
    local state = buffers[buf]
    if state and api.nvim_buf_is_loaded(buf) then
      local checked = state.checked
      local ok, err = pcall(vim.cmd.checktime, buf)
      if not ok then
        vim.notify("checktime: " .. err, vim.log.levels.WARN)
      elseif from_fs and buffers[buf] == state and state.checked == checked then
        -- checktime compares timestamps/mode, not inode/size: real writes can share an mtime.
        local stat = uv.fs_stat(state.name)
        if stat and stat.type == "file" then reread(buf) end
      end
    end
  end
  checking = false
end

local function track(buf)
  if not active or not api.nvim_buf_is_loaded(buf) then return end
  local name = api.nvim_buf_get_name(buf)
  if vim.bo[buf].buftype ~= "" or name == "" then
    detach(buf)
    return
  end
  local parent = vim.fs.dirname(name)
  local state = buffers[buf]
  if state and state.name == name then return end
  detach(buf)
  state = { name = name, dir = parent, autoread = vim.bo[buf].autoread, generation = 0, checked = 0 }
  buffers[buf] = state
  -- autoread would bypass FileChangedShell for clean buffers, losing the pre-reload text.
  vim.bo[buf].autoread = false
  local dir = dirs[parent]
  if not dir then
    dir = { buffers = {}, watcher = uv.new_fs_event(), timer = uv.new_timer() }
    dirs[parent] = dir
    local ok = dir.watcher:start(parent, {}, function(err, filename)
      if err or not active or dirs[parent] ~= dir then return end
      for watched in pairs(dir.buffers) do
        local current = buffers[watched]
        if current and (not filename or vim.fs.basename(current.name) == filename) then pending[watched] = true end
      end
      dir.timer:start(100, 0, vim.schedule_wrap(function()
        if dirs[parent] == dir then flush() end
      end))
    end)
    if not ok then
      close(dir.watcher)
      dir.watcher = nil -- Native focus/buffer-entry checks still work if the directory cannot be watched.
    end
  end
  dir.buffers[buf] = true
end

highlight = function(buf, old)
  local state = buffers[buf]
  if not state or not api.nvim_buf_is_loaded(buf) then return end
  local new = api.nvim_buf_get_lines(buf, 0, -1, false)
  local hunks = vim.text.diff(table.concat(old, "\n") .. "\n", table.concat(new, "\n") .. "\n", {
    result_type = "indices", algorithm = "histogram",
  })
  if #hunks == 0 then return end
  api.nvim_buf_clear_namespace(buf, ns, 0, -1)
  local added, removed = 0, 0
  for _, hunk in ipairs(hunks) do
    local old_count, start, count = hunk[2], hunk[3], hunk[4]
    added, removed = added + count, removed + old_count
    if count == 0 then
      api.nvim_buf_set_extmark(buf, ns, math.max(0, math.min(start - 1, #new - 1)), 0, {
        sign_text = "▁", sign_hl_group = "ExternalEditSign", priority = 5,
      })
    else
      for row = start - 1, start + count - 2 do
        api.nvim_buf_set_extmark(buf, ns, row, 0, {
          line_hl_group = "ExternalEditLine", sign_text = "▎", sign_hl_group = "ExternalEditSign", priority = 5,
        })
      end
    end
  end
  vim.notify(("%s: внешние правки +%d −%d"):format(vim.fs.basename(state.name), added, removed), vim.log.levels.INFO)
  state.generation = state.generation + 1
  local generation = state.generation
  state.expiry = state.expiry or uv.new_timer()
  state.expiry:start(10000, 0, vim.schedule_wrap(function()
    if buffers[buf] == state and state.generation == generation and api.nvim_buf_is_valid(buf) then
      api.nvim_buf_clear_namespace(buf, ns, 0, -1)
      close(state.expiry)
      state.expiry = nil
    end
  end))
end

function M.stop()
  active = false
  if group then api.nvim_del_augroup_by_id(group); group = nil end
  for buf in pairs(buffers) do detach(buf) end
  if original_autoread ~= nil then vim.o.autoread = original_autoread end
  original_autoread = nil
end

function M.setup()
  M.stop()
  active = true
  original_autoread = vim.o.autoread
  vim.o.autoread = false
  group = api.nvim_create_augroup("user_external_changes", { clear = true })
  local function colors()
    api.nvim_set_hl(0, "ExternalEditLine", { default = true, link = "DiffChange" })
    api.nvim_set_hl(0, "ExternalEditSign", { default = true, link = "DiffAdd" })
  end
  colors()
  api.nvim_create_autocmd("ColorScheme", { group = group, callback = colors })
  api.nvim_create_autocmd({ "BufReadPost", "BufNewFile", "BufWritePost", "BufFilePost" }, {
    group = group, callback = function(a) track(a.buf) end,
  })
  api.nvim_create_autocmd({ "BufUnload", "BufDelete", "BufWipeout" }, {
    group = group, callback = function(a) detach(a.buf) end,
  })
  api.nvim_create_autocmd({ "FocusGained", "BufEnter" }, {
    group = group,
    callback = function()
      for buf in pairs(buffers) do
        if pending[buf] == nil then pending[buf] = false end -- Focus checks are not filesystem writes.
      end
      vim.schedule(flush)
    end,
  })
  api.nvim_create_autocmd("ModeChanged", {
    group = group, pattern = "*:n", callback = function() vim.schedule(flush) end,
  })
  api.nvim_create_autocmd("FileChangedShell", {
    group = group,
    callback = function(a)
      if not buffers[a.buf] then return end
      buffers[a.buf].checked = buffers[a.buf].checked + 1
      before[a.buf] = nil
      if vim.bo[a.buf].modified or vim.v.fcs_reason == "deleted" then
        vim.v.fcs_choice = "ask"
      elseif vim.v.fcs_reason == "changed" then
        before[a.buf] = api.nvim_buf_get_lines(a.buf, 0, -1, false)
        vim.v.fcs_choice = "reload"
      else
        vim.v.fcs_choice = "ask"
      end
    end,
  })
  api.nvim_create_autocmd("FileChangedShellPost", {
    group = group,
    callback = function(a)
      local old = before[a.buf]
      before[a.buf] = nil
      if old then highlight(a.buf, old) end
    end,
  })
  api.nvim_create_autocmd("VimLeavePre", { group = group, callback = M.stop })
  for _, buf in ipairs(api.nvim_list_bufs()) do track(buf) end
end

return M
