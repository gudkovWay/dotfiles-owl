return {
  {
    "folke/snacks.nvim",
    priority = 1000,
    lazy = false,
    keys = {
      { "<leader>e", "<cmd>lua Snacks.explorer()<cr>", desc = "file explorer" },
      -- терминальная панель как в VSCode. Счёт-префикс даёт инстансы
      -- (2<leader>o — второй omp, 2<leader>tt — второй shell): счёт уходит
      -- в id терминала snacks. Спавн omp тот же, что kitty ctrl+shift+n.
      -- Из панели наружу: <esc><esc>/jk/jj → normal, q — скрыть, а из
      -- самого terminal-mode работает навигация C-h/j/k/l/\ (win.keys).
      {
        "<leader>o",
        function() Snacks.terminal.toggle({ "fish", "-C", "omp --allow-home" }) end,
        desc = "omp terminal",
      },
      {
        "<leader>tt",
        function() Snacks.terminal.toggle() end,
        desc = "terminal (fish)",
      },
    },
    opts = {
      explorer = {
        enabled = true,
        -- дерево файлов: devicons, git-статусы; правки в дереве
        replace_netrw = true,
      },
      dashboard = {
        preset = {
          -- подписи/хоткеи — дефолтные (английские); меняется только пикер:
          -- фронтенд выбора — fzf-lua (уже в конфиге), не snacks.picker
          pick = function(cmd, opts)
            local map = { files = "files", oldfiles = "oldfiles", grep = "live_grep" }
            return require("fzf-lua")[map[cmd] or cmd](opts)
          end,
        },
      },
      -- нижний сплит и для терминалов с cmd (дефолт snacks при cmd — float).
      -- win.keys — buffer-local: мержатся со стилем snacks (q, gf, двойной
      -- <esc>) и живут только в этих панелях. Глобальные t-карты не трогаем:
      -- fzf-lua тоже работает в terminal-буферах, ему нужен сырой ввод.
      terminal = {
        win = {
          position = "bottom",
          height = 0.35,
          keys = {
            -- навигация изнутри панели: сначала выход в normal, дальше
            -- обычный маршрут навигатора (plugins/tmux.lua + tmux.conf).
            -- Цена: C-h/j/k/l и C-\ внутри панели больше не доходят до
            -- приложения (fish/omp) как управляющие символы.
            nav_left = { "<C-h>", [[<C-\><C-n><cmd>TmuxNavigateLeft<cr>]], mode = "t", expr = true, desc = "navigate left" },
            nav_down = { "<C-j>", [[<C-\><C-n><cmd>TmuxNavigateDown<cr>]], mode = "t", expr = true, desc = "navigate down" },
            nav_up = { "<C-k>", [[<C-\><C-n><cmd>TmuxNavigateUp<cr>]], mode = "t", expr = true, desc = "navigate up" },
            nav_right = { "<C-l>", [[<C-\><C-n><cmd>TmuxNavigateRight<cr>]], mode = "t", expr = true, desc = "navigate right" },
            nav_prev = { [[<C-\>]], [[<C-\><C-n><cmd>TmuxNavigatePrevious<cr>]], mode = "t", expr = true, desc = "navigate prev pane" },
            -- выход из terminal-mode теми же биграммами, что и в insert
            -- (config/keymaps.lua): панель живёт, omp работает дальше.
            -- expr обязателен: строковый rhs в win.keys snacks — это имя
            -- action ("hide" и т.п.), клавиатурная последовательность
            -- возвращается только из expr-карты.
            term_jk = { "jk", [[<C-\><C-n>]], mode = "t", expr = true, desc = "terminal normal mode" },
            term_jj = { "jj", [[<C-\><C-n>]], mode = "t", expr = true, desc = "terminal normal mode" },
            term_ol = { "ол", [[<C-\><C-n>]], mode = "t", expr = true, desc = "terminal normal mode" },
            term_oo = { "оо", [[<C-\><C-n>]], mode = "t", expr = true, desc = "terminal normal mode" },
          },
        },
      },
    },
  },
}
