local M = {}
local errors = {}
function M.check_errors()
  assert(#errors == 0, 'plugin errors: ' .. table.concat(errors, '\n'))
end
function M.start()
  -- v:errmsg also retains intentionally silent cleanup failures (e.g. missing netrw group).
  local notify = vim.notify
  vim.notify = function(message, level, opts)
    if level and level >= vim.log.levels.ERROR then errors[#errors + 1] = tostring(message) end
    return notify(message, level, opts)
  end
  local config = vim.fn.stdpath('config')
  vim.opt.runtimepath:prepend(config)
  vim.opt.runtimepath:prepend(vim.fn.stdpath('data') .. '/lazy/lazy.nvim')
  -- Isolated library defaults forbid installs even if the user's setup ignores its second argument.
  local defaults = require('lazy.core.config').defaults
  defaults.install.missing = false
  defaults.checker.enabled = false
  defaults.change_detection.enabled = false
  dofile(config .. '/init.lua')
  -- -l does not finish normal editor startup; enable its standard filetype events explicitly.
  vim.cmd('filetype plugin indent on')
  assert(_G.__CFG_OK, 'full Neovim config failed to initialize')
  M.check_errors()
end
return M
