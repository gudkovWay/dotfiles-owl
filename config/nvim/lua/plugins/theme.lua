return {
  -- статичная палитра (config/palette.lua) поверх base16; грузим сразу —
  -- тема нужна на старте
  {
    "RRethy/base16-nvim",
    lazy = false,
    config = function()
      require("config.theme").setup()
    end,
  },
}
