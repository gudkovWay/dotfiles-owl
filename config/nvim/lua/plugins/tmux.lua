-- Бесшовная навигация nvim <-> tmux: C-h/j/k/l между сплитами nvim и
-- панелями tmux едиными клавишами, C-\ — предыдущий сплит/панель.
-- У края nvim-сплита плагин сам дёргает tmux select-pane. Тmux-сторона
-- с тем же is_vim-паттерном — в ~/.config/tmux/tmux.conf.
return {
  "christoomey/vim-tmux-navigator",
  lazy = false,
}
