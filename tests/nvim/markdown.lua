local api = vim.api
local helper = dofile(vim.env.NVIM_TEST_REPO .. '/tests/nvim/helpers.lua')
helper.start()
local source = {
  '# Heading', '', '- item', '',
  '| Name | Value |', '| --- | --- |', '| alpha | beta |', '',
  '```lua', 'local answer = 42', '```', '', 'cursor here',
}
local path = vim.env.NVIM_TEST_TMP .. '/reading.md'
vim.fn.writefile(source, path)
vim.cmd.edit(path)
local buf = api.nvim_get_current_buf()
assert(vim.bo[buf].filetype == 'markdown', 'Markdown filetype was not detected')
api.nvim_win_set_cursor(0, { #source, 0 })
local parser = assert(vim.treesitter.get_parser(buf, 'markdown'), 'Markdown parser unavailable')
parser:parse(true)
assert(parser:children().lua, 'fenced Lua code did not receive language highlighting')
assert(vim.treesitter.language.add('markdown_inline'), 'inline Markdown parser unavailable')
local renderer = require('render-markdown')
local function decorations()
  local result = {}
  for name, ns in pairs(api.nvim_get_namespaces()) do
    if name:find('render%-markdown') then
      for _, mark in ipairs(api.nvim_buf_get_extmarks(buf, ns, 0, -1, { details = true })) do
        result[#result + 1] = mark
      end
    end
  end
  return result
end
local function rendered()
  local heading, table_border, code = false, false, false
  for _, mark in ipairs(decorations()) do
    local row, opts = mark[2], mark[4]
    if row == 0 and opts.virt_text then heading = true end
    if row >= 4 and row <= 6 and opts.virt_text then table_border = true end
    if row >= 8 and row <= 10 and (opts.hl_group or opts.line_hl_group or opts.virt_text) then code = true end
  end
  return heading and table_border and code
end
assert(vim.wait(3000, rendered, 20), 'heading/table/code decorations were not rendered')
assert(vim.deep_equal(api.nvim_buf_get_lines(buf, 0, -1, false), source), 'rendering rewrote Markdown source')
assert(not vim.bo[buf].modified, 'rendering dirtied Markdown buffer')
-- Let the renderer's documented 100 ms debounce finish before the next user action.
vim.wait(150)
renderer.disable()
assert(vim.wait(2000, function() return #decorations() == 0 end, 20), 'raw view retained rendered decorations')
assert(vim.deep_equal(api.nvim_buf_get_lines(buf, 0, -1, false), source), 'raw view lost source syntax')
vim.wait(150)
renderer.enable()
assert(vim.wait(3000, rendered, 20), 'rendering did not resume')
helper.check_errors()
print('markdown: full config, real parsers, heading/table/code render and raw-source round trip passed')
