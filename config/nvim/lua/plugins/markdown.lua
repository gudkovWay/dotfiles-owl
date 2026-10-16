return {
  {
    "MeanderingProgrammer/render-markdown.nvim",
    commit = "640a3ec6d538bad17c328be373c7cad0293d9589", -- v8.14.0
    ft = "markdown",
    dependencies = { "nvim-treesitter/nvim-treesitter", "nvim-tree/nvim-web-devicons" },
    opts = {
      file_types = { "markdown" },
      render_modes = { "n", "c", "t" },
      -- Только оформление текста: без внешних конвертеров формул и загрузки картинок.
      latex = { enabled = false },
      heading = { sign = false },
      code = { sign = false, width = "block", border = "thin" },
      pipe_table = { preset = "round" },
    },
  },
}
