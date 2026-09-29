return {
  {
    "stevearc/conform.nvim",
    -- грузим на открытии буфера, не на записи: с BufWritePre плагин
    -- загружается В МОМЕНТ первого события и опаздывает к нему же
    -- (первое сохранение не форматировало); BufReadPre гарантированно раньше
    event = { "BufReadPre", "BufNewFile" },
    cmd = { "ConformInfo" },
    opts = {
      formatters_by_ft = {
        lua = { "stylua" },
        vue = { "prettier" },
        javascript = { "prettier" },
        typescript = { "prettier" },
        typescriptreact = { "prettier" },
        go = { "gofmt" },
      },
      -- format_on_save конформа не используем: порядок с eslint-фиксами
      -- задаём сами в config (см. ниже)
    },
    config = function(_, opts)
      local conform = require("conform")
      conform.setup(opts)

      -- eslint.applyAllFixes — синхронная серверная команда vscode-eslint;
      -- применяет все fixable-правила, в т.ч. tailwindcss/classnames-order
      -- (сортировка tailwind-классов) и prettier/prettier там, где проект
      -- гоняет prettier через eslint (p2p-frontend/ecom-frontend).
      local function eslint_fix_all(bufnr)
        for _, client in ipairs(vim.lsp.get_clients({ bufnr = bufnr, name = "eslint" })) do
          client:request_sync("workspace/executeCommand", {
            command = "eslint.applyAllFixes",
            arguments = {
              {
                uri = vim.uri_from_bufnr(bufnr),
                version = vim.lsp.util.buf_versions[bufnr],
              },
            },
          }, 3000, bufnr)
        end
      end

      -- Порядок шагов важен и поэтому зафиксирован в одной автокоманде, а не
      -- разнесён по format_on_save + LspAttach (там очередь зависела бы от
      -- времени регистрации хуков). Сначала eslint: серверу нужна та версия
      -- документа, которую он уже видел, иначе applyAllFixes молча отбрасывает
      -- правки как устаревшие. Затем prettier (stylua/gofmt для прочих ft)
      -- добивает форматирование.
      vim.api.nvim_create_autocmd("BufWritePre", {
        group = vim.api.nvim_create_augroup("user-format-on-save", { clear = true }),
        callback = function(args)
          eslint_fix_all(args.buf)
          conform.format({ bufnr = args.buf, timeout_ms = 1000, lsp_format = "fallback" })
        end,
      })
    end,
  },
}
