return {
  {
    "nvim-treesitter/nvim-treesitter",
    build = ":TSUpdate",
    -- триггер обязателен: спека без event/cmd при defaults.lazy=true
    -- вообще не грузится (потеряли при порте из NvChad — там грузило ядро),
    -- и ensure_installed никогда не выполняется
    event = { "BufReadPost", "BufNewFile" },
    -- через lazy парсеры не ставит (проверено: vue.so отсутствует в rtp),
    -- highlight-модуль тоже переписан. Плюс страховочный нативный attach
    -- в config/autocmds.lua (vim.treesitter.start по FileType).
    branch = "master",
    opts = {
      ensure_installed = {
        "vim", "lua", "vimdoc", "html", "css",
        "javascript", "typescript", "tsx", "vue",
        "python", "go",
      },
      highlight = { enable = true },
    },
  },

  -- закрытие парных тегов в vue/html/jsx (портировано)
  {
    "windwp/nvim-ts-autotag",
    event = "BufReadPre",
    opts = {},
  },
}
