return {
  {
    "mikavilpas/yazi.nvim",
    event = "VeryLazy",
    keys = {
      { "<leader>-", "<cmd>Yazi<cr>", desc = "yazi at current file" },
      { "<leader>cw", "<cmd>Yazi cwd<cr>", desc = "yazi in working dir" },
      { "<c-up>", "<cmd>Yazi toggle<cr>", desc = "resume yazi session" },
    },
    opts = {
      -- nvim somedir открывает yazi вместо файлового браузера
      open_for_directories = true,
    },
  },
}
