local root = vim.env.NVIM_TEST_TMP
vim.fn.mkdir(root .. '/hostile-module', 'p')
vim.fn.writefile({ '_G.cwd_module_executed = true; return {}' }, root .. '/cwd_shadow.lua')
vim.fn.writefile({ '_G.cwd_init_executed = true; return {}' }, root .. '/hostile-module/init.lua')
vim.fn.writefile({ '_G.project_exrc_executed = true' }, root .. '/.nvim.lua')
vim.fn.writefile({ '_G.project_lazy_executed = true; return {}' }, root .. '/.lazy.lua')
vim.cmd.cd(root)
package.path = './?.lua;./?/init.lua;' .. package.path
package.cpath = './?.so;' .. package.cpath
local safe_path = root .. '/safe/?.lua'
vim.fn.mkdir(root .. '/safe', 'p')
vim.fn.writefile({ 'return { value = 42 }' }, root .. '/safe/trusted_module.lua')
package.path = package.path .. ';' .. safe_path

local helper = dofile(vim.env.NVIM_TEST_REPO .. '/tests/nvim/helpers.lua')
helper.start()
local ok = pcall(require, 'cwd_shadow')
assert(not ok and not _G.cwd_module_executed, 'cwd Lua module was executed')
ok = pcall(require, 'hostile-module')
assert(not ok and not _G.cwd_init_executed, 'cwd Lua init module was executed')
assert(require('trusted_module').value == 42, 'absolute Lua module paths were broken')
assert(not vim.o.exrc and not _G.project_exrc_executed, 'project-local config was enabled')
local file = root .. '/modeline.txt'
vim.fn.writefile({ 'ordinary text', ' vim: set tabstop=19 shiftwidth=19:' }, file)
assert(not _G.project_lazy_executed, 'lazy.nvim executed a project-local spec')
vim.cmd.edit(file)
assert(vim.bo.tabstop ~= 19 and vim.bo.shiftwidth ~= 19, 'file modeline changed buffer options')
helper.check_errors()
print('security: cwd shadowing/modeline/exrc protection and trusted absolute imports passed')
