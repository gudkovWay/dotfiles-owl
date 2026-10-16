return {
  {
    "nvim-treesitter/nvim-treesitter",
    build = ":TSUpdate",
    -- триггер обязателен: спека без event/cmd при defaults.lazy=true
    -- вообще не грузится (потеряли при порте из NvChad — там грузило ядро),
    -- и ensure_installed никогда не выполняется
    event = { "BufReadPost", "BufNewFile" },
    -- Закреплённая master-ветка принимает опции через configs.setup.
    -- Нативный FileType-attach в config/autocmds.lua остаётся страховкой.
    branch = "master",
    opts = {
      ensure_installed = {
        "vim", "lua", "vimdoc", "html", "css",
        "javascript", "typescript", "tsx", "vue",
        "python", "go", "markdown", "markdown_inline",
      },
      highlight = { enable = true },
    },
    config = function(_, opts)
      require("nvim-treesitter.configs").setup(opts)
    end,
  },

  -- закрытие парных тегов в vue/html/jsx (портировано)
  {
    "windwp/nvim-ts-autotag",
    event = "BufReadPre",
    opts = {},
  },
}
