return {
  {
    "Saghen/blink.cmp",
    version = "1.*", -- v2 в активной разработке; стабильная ветка — 1.x
    event = "InsertEnter",
    -- AI-автодополнение ушло в ghost-текст (minuet virtualtext); в меню blink — только
    -- lsp/path/buffer/snippets. Пресет enter: <CR> принять, <C-y> свободен.
    opts = {
      keymap = { preset = "enter" },
      sources = {
        default = { "lsp", "path", "buffer", "snippets" },
      },
      completion = {
        trigger = { prefetch_on_insert = false },
        documentation = { auto_show = true, window = { border = "rounded" } },
      },
    },
  },
}
