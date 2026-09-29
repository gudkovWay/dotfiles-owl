-- which-key: подсказка по доступным биндам. Popup по паузе после <leader>
-- (и других префиксов); описания подтягиваются из desc у keymap'ов.
return {
  "folke/which-key.nvim",
  event = "VeryLazy",
  opts = {
    preset = "classic",
  },
}
