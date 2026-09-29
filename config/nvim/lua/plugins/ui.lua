return {
  -- вкладки буферов сверху (то, чего больше всего не хватало после NvChad)
  {
    "akinsho/bufferline.nvim",
    version = "*",
    dependencies = { "nvim-tree/nvim-web-devicons" },
    -- VimEnter, не BufAdd: для файла, открытого аргументом, BufAdd событие
    -- ленивой загрузки не срабатывает; VimEnter надёжен всегда
    event = "VimEnter",
    opts = {
      options = {
        mode = "buffers",
        numbers = "ordinal",       -- 1/2/3 на вкладках — под Ctrl-<цифра>
        diagnostics = "nvim_lsp",
        offsets = {
          {
            filetype = "snacks_layout_box",
            text = "Explorer",
            text_align = "center",
          },
        },
      },
    },
  },

  -- гит в жёлобе: +/-/~, навигация по изменённым кускам, ветка для статус-лайна
  {
    "lewis6991/gitsigns.nvim",
    event = "BufReadPre",
    opts = {},
  },

  -- вертикальные индент-гайды (+ подсветка текущего scope)
  {
    "lukas-reineke/indent-blankline.nvim",
    main = "ibl",
    event = "BufReadPost",
    opts = {
      scope = { enabled = true },
    },
  },
}
