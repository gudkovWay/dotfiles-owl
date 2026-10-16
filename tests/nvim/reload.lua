local api, uv = vim.api, vim.uv
vim.opt.runtimepath:prepend(vim.fn.stdpath('config'))
local reload = require('config.autoreload')
local path = vim.env.NVIM_TEST_TMP .. '/agent.txt'
local ns = api.nvim_create_namespace('user_external_changes')
local notices, choices = {}, {}
vim.notify = function(message) notices[#notices + 1] = message end

local function wait_for(test, message, timeout)
  if not vim.wait(timeout or 3000, test, 20) then
    local stat = uv.fs_stat(path)
    error(message .. ': ' .. vim.inspect({
      mode = api.nvim_get_mode().mode, disk = stat and { size = stat.size, mtime = stat.mtime },
      buffer = api.nvim_buf_get_lines(0, 0, -1, false), notices = notices,
    }))
  end
end
local function write(lines, atomic, mtime)
  local dest = atomic and (path .. '.new') or path
  vim.fn.writefile(lines, dest)
  if mtime then assert(uv.fs_utime(dest, mtime, mtime)) end
  if atomic then assert(uv.fs_rename(dest, path)) end
end
local function lines(buf) return api.nvim_buf_get_lines(buf, 0, -1, false) end
local function marks(buf) return api.nvim_buf_get_extmarks(buf, ns, 0, -1, { details = true }) end
local function handles()
  local count = 0
  uv.walk(function(handle)
    if handle:get_type() == 'fs_event' and not handle:is_closing() then count = count + 1 end
  end)
  return count
end

-- Equal timestamps occur with fast writes or tools preserving mtimes: inode/size must still count.
local unchanged_mtime = os.time() - 60
write({ 'before', 'second', 'third' }, false, unchanged_mtime)
local baseline = handles()
reload.setup()
vim.cmd.edit(path)
local buf = api.nvim_get_current_buf()
-- The headless test declines native conflict/deletion dialogs, after recording the production choice.
api.nvim_create_autocmd('FileChangedShell', {
  callback = function(a)
    if vim.bo[a.buf].modified or vim.v.fcs_reason == 'deleted' then
      choices[#choices + 1] = { reason = vim.v.fcs_reason, choice = vim.v.fcs_choice }
      vim.v.fcs_choice = ''
    end
  end,
})

write({ 'agent edited this line', 'second', 'third' }, false, unchanged_mtime)
wait_for(function() return lines(buf)[1] == 'agent edited this line' end, 'external write was not reloaded')
assert(not vim.bo[buf].modified, 'external reload dirtied buffer')
assert(marks(buf)[1][2] == 0 and marks(buf)[1][4].line_hl_group, 'changed first line is not highlighted')
assert(notices[#notices]:find('+1') and notices[#notices]:find('−1'), 'missing external diff notification')

write({ 'atomic replacement one is longer', 'second', 'third' }, true, unchanged_mtime)
wait_for(function() return lines(buf)[1] == 'atomic replacement one is longer' end, 'first atomic write missed')
write({ 'atomic replacement two', 'second', 'third' }, true, unchanged_mtime)
wait_for(function() return lines(buf)[1] == 'atomic replacement two' end, 'watch detached after atomic rename')

-- A shared directory watcher must survive closing one of its subscribed buffers.
local peer = vim.env.NVIM_TEST_TMP .. '/peer.txt'
vim.fn.writefile({ 'peer' }, peer)
vim.cmd.edit(peer)
local peerbuf = api.nvim_get_current_buf()
api.nvim_buf_delete(peerbuf, { force = true })
api.nvim_set_current_buf(buf)
write({ 'watched after peer closed', 'second', 'third' })
wait_for(function() return lines(buf)[1] == 'watched after peer closed' end, 'closing peer broke directory watch')

-- External reload must not interrupt a selection, and must resume when it is cancelled.
api.nvim_feedkeys('v', 'xt', false)
assert(api.nvim_get_mode().mode == 'v', 'test did not enter Visual mode')
write({ 'agent write during selection', 'second', 'third' }, true)
vim.wait(250)
assert(lines(buf)[1] == 'watched after peer closed', 'background reload interrupted Visual mode')
api.nvim_feedkeys(api.nvim_replace_termcodes('<Esc>', true, false, true), 'xt', false)
wait_for(function() return lines(buf)[1] == 'agent write during selection' end, 'pending reload lost after leaving Visual mode')

api.nvim_buf_set_lines(buf, 0, 1, false, { 'unsaved local work' })
write({ 'different external version', 'second', 'third' }, true)
wait_for(function() return #choices > 0 end, 'modified buffer conflict was not detected')
assert(choices[#choices].choice == 'ask', 'dirty buffer did not ask before reload')
assert(lines(buf)[1] == 'unsaved local work' and vim.bo[buf].modified, 'unsaved edits were overwritten')
assert(vim.fn.readfile(path)[1] == 'different external version', 'reload wrote local edits to disk')

-- Check the native confirmation boundary when timestamps cannot expose a conflict.
assert(uv.fs_utime(path, unchanged_mtime, unchanged_mtime))
vim.cmd.checktime(buf) -- Decline this ordinary timestamp conflict via the handler above.
local confirm, confirmations = vim.fn.confirm, 0
vim.fn.confirm = function()
  confirmations = confirmations + 1
  return 2 -- Keep unsaved edits.
end
write({ 'mtime-preserving external version', 'second', 'third' }, true, unchanged_mtime)
wait_for(function() return confirmations > 0 end, 'same-timestamp conflict did not ask')
assert(lines(buf)[1] == 'unsaved local work' and vim.bo[buf].modified, 'same-timestamp write overwrote unsaved edits')
assert(vim.fn.readfile(path)[1] == 'mtime-preserving external version', 'declining reload changed disk')
vim.fn.confirm = function() return 1 end -- Explicit user approval may discard the local version.
write({ 'approved external version', 'second', 'third' }, true, unchanged_mtime)
wait_for(function() return lines(buf)[1] == 'approved external version' end, 'approved conflict reload failed')
assert(not vim.bo[buf].modified, 'approved reload left buffer dirty')
vim.fn.confirm = confirm

vim.cmd('edit!')
write({ 'approved external version' }, true)
wait_for(function() return #lines(buf) == 1 end, 'pure line deletion not reloaded')
local deletion = marks(buf)[1]
assert(deletion and deletion[2] == 0 and deletion[4].sign_text and not deletion[4].line_hl_group,
  'pure deletion must mark its anchor, not highlight an unchanged line: ' .. vim.inspect(deletion))
assert(notices[#notices]:find('+0') and notices[#notices]:find('−2'), 'incorrect pure-deletion counts')

-- Old expiry must not erase a newer edit's highlight; exercise the real ten-second lifetime.
vim.wait(5200)
write({ 'newer edit must stay highlighted past the first deadline' }, true)
wait_for(function() return lines(buf)[1] == 'newer edit must stay highlighted past the first deadline' end, 'newer edit missed')
vim.wait(5100)
assert(#marks(buf) > 0, 'old expiry erased newer highlight')
wait_for(function() return #marks(buf) == 0 end, 'highlight never expired', 6000)

assert(uv.fs_unlink(path))
wait_for(function() return choices[#choices].reason == 'deleted' end, 'deleted file not reported')
assert(api.nvim_buf_is_valid(buf) and #lines(buf) == 1, 'deleted file discarded buffer')
api.nvim_buf_delete(buf, { force = true })
wait_for(function() return handles() == baseline end, 'watcher leaked after last subscriber closed')

-- Deployed dotfiles are symlinks: observe writes to their real target directory.
local targetdir = vim.env.NVIM_TEST_TMP .. '/source'
vim.fn.mkdir(targetdir, 'p')
local target, alias = targetdir .. '/real.txt', vim.env.NVIM_TEST_TMP .. '/alias.txt'
vim.fn.writefile({ 'symlink before' }, target)
assert(uv.fs_symlink(target, alias))
vim.cmd.edit(alias)
local linked = api.nvim_get_current_buf()
vim.fn.writefile({ 'symlink target updated atomically' }, target .. '.new')
assert(uv.fs_rename(target .. '.new', target))
wait_for(function() return lines(linked)[1] == 'symlink target updated atomically' end, 'symlink target write missed')
api.nvim_buf_delete(linked, { force = true })
wait_for(function() return handles() == baseline end, 'symlink watcher leaked')

write({ 'setup can be repeated' })
vim.cmd.edit(path)
reload.setup()
write({ 'still watched after repeated setup' }, true)
wait_for(function() return lines(api.nvim_get_current_buf())[1] == 'still watched after repeated setup' end, 'repeated setup lost watch')
reload.stop()
wait_for(function() return handles() == baseline end, 'stop leaked watchers')
print('reload: external/atomic/dirty/deletion/expiry/cleanup scenarios passed')
