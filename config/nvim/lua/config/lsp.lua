-- LSP на нативном vim.lsp.config / vim.lsp.enable (nvim 0.11+).
-- vue takeover (см. ниже), набор серверов портирован из NvChad (10.09.2026),
-- добавлены lua_ls (сам конфиг) и gopls. Бинарки ставятся Mason'ом
-- (см. plugins/lsp.lua; большая часть — с NvChad-времени) и должны быть
-- в PATH до vim.lsp.enable, иначе конфиги серверов молча роняются
-- («invalid config»).
vim.env.PATH = vim.fn.stdpath("data") .. "/mason/bin:" .. vim.env.PATH

-- Vue (v3, только гибрид — takeover удалён в vue-language-server 3.0):
--   vue_ls — CSS/HTML-секции .vue;
--   vtsls  — TypeScript в .vue через @vue/typescript-plugin (globalPlugins).
-- Проверено на p2p-frontend: связка ts_ls+init_options.plugins аттачится
-- и резолвит алиасы, но определения в script-блоках не даёт — канонический
-- рецепт nvim-lspconfig требует именно vtsls.
local vue_pkg = vim.fn.stdpath("data") .. "/mason/packages/vue-language-server/node_modules"

if vim.uv.fs_stat(vue_pkg .. "/@vue/typescript-plugin") then
  vim.lsp.config("vue_ls", {
    init_options = {
      vue = { hybridMode = true },
      typescript = { tsdk = vue_pkg .. "/typescript/lib" },
    },
  })

  vim.lsp.config("vtsls", {
    filetypes = { "javascript", "javascriptreact", "typescript", "typescriptreact", "vue" },
    settings = {
      vtsls = {
        tsserver = {
          globalPlugins = {
            {
              name = "@vue/typescript-plugin",
              location = vue_pkg .. "/@vue/typescript-plugin",
              languages = { "vue" },
              enabledForWorkspaceTypeScriptVersions = true,
            },
          },
        },
      },
    },
  })
end


vim.lsp.config("lua_ls", {
  settings = {
    Lua = {
      runtime = { version = "LuaJIT" },
      diagnostics = { globals = { "vim" } },
      workspace = { checkThirdParty = false },
    },
  },
})

vim.lsp.enable({
  "html",
  "cssls",
  "vtsls",
  "vue_ls",
  "eslint",
  "pyright",
  "lua_ls",
  "gopls",
})

-- диагностика: аккуратная, без спама во время ввода
vim.diagnostic.config({
  virtual_text = { spacing = 2, prefix = "●" },
  severity_sort = true,
  underline = true,
  update_in_insert = false,
})

-- nvim 0.11+ биндит на LSP только grr/gri; нативный gd — поиск локальных
-- объявлений (не LSP), gf — родной go-to-file (не трогаем). Поэтому
-- gd/gD/gy мапим на LSP явно здесь.
vim.api.nvim_create_autocmd("LspAttach", {
  group = vim.api.nvim_create_augroup("user-lsp", { clear = true }),
  callback = function(event)
    local map = function(lhs, rhs, desc)
      vim.keymap.set("n", lhs, rhs, { buffer = event.buf, desc = "lsp: " .. desc })
    end
    map("<leader>rn", vim.lsp.buf.rename, "rename")
    map("<leader>ca", vim.lsp.buf.code_action, "code action")
    map("<leader>fm", function() vim.lsp.buf.format({ async = true }) end, "format")
    map("gd", vim.lsp.buf.definition, "goto definition")
    map("gD", vim.lsp.buf.declaration, "goto declaration")
    map("gy", vim.lsp.buf.type_definition, "goto type definition")
  end,
})
