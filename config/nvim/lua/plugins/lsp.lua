return {
  -- нативные конфиги серверов для vim.lsp.enable (сами конфиги — config/lsp.lua)
  {
    -- BufReadPre: enable() в config/lsp.lua регистрирует FileType-хуки
    -- до срабатывания FileType, серверы цепляются как раньше, но ~rtp-скан
    -- 60 конфигов уезжает с горячего пути старта
    "neovim/nvim-lspconfig",
    event = { "BufReadPre", "BufNewFile" },
    config = function()
      require("config.lsp")
    end,
  },

  -- только установка бинарков; в старте не участвует
  {
    "mason-org/mason.nvim",
    cmd = { "Mason", "MasonInstall", "MasonUpdate", "MasonUninstall" },
    opts = {},
  },
}
