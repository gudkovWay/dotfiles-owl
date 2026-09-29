-- Ключ DEEPSEEK_API_KEY берём сначала из окружения; если его нет (nvim
-- из долгоживущей оболочки, стартовавшей раньше экспорта, или из
-- systemd-контекста), добираем из файла внешнего приватного хранилища
-- ${XDG_CONFIG_HOME:-$HOME/.config}/dotfiles-owl-private/keys/deepseek —
-- единственного места хранения, дублей не создаём.
--
-- Резолвер отдаётся Minuet как функция api_key: провайдер зовёт её сам —
-- при проверке доступности и при сборке запроса, — поэтому найденный ключ
-- живёт в локальном кеше конфига и в окружение процесса (vim.env) не
-- попадает. Без ключа плагин не грузим вовсе: нет кеймапов, нет
-- авто-триггера, нет трейсбеков (openai_base.lua:152 конкатенирует
-- 'Bearer ' с nil).
local cached_api_key

local function resolve_api_key()
  if cached_api_key then
    return cached_api_key
  end

  local key = vim.env.DEEPSEEK_API_KEY
  if not key or key == "" then
    local cfg = vim.env.XDG_CONFIG_HOME
    if not cfg or cfg == "" then
      cfg = vim.env.HOME .. "/.config"
    end

    local ok, lines = pcall(vim.fn.readfile, cfg .. "/dotfiles-owl-private/keys/deepseek")
    if ok and not vim.tbl_isempty(lines) then
      key = vim.trim(table.concat(lines, "\n"))
      if key == "" then
        key = nil
      end
    else
      key = nil
    end
  end

  cached_api_key = key
  return key
end

return {
  {
    "milanglacier/minuet-ai.nvim",
    event = { "BufReadPre", "BufNewFile" },
    cond = function()
      if resolve_api_key() then
        return true
      end
      vim.schedule(function()
        vim.notify(
          "minuet: DEEPSEEK_API_KEY не найден (ни в env, ни в dotfiles-owl-private/keys/deepseek)"
            .. " — автодополнение отключено",
          vim.log.levels.WARN
        )
      end)
      return false
    end,
    -- Автодополнение ghost-текстом (virtualtext), а не в меню blink.
    -- Провайдер: прямой DeepSeek FIM API (openai_fim_compatible), модель
    -- deepseek-flash. api_key — функция resolve_api_key: её зовёт сам Minuet
    -- (проверка провайдера + сборка запроса), так что ключ живёт только в
    -- памяти этого конфига, а не в окружении процесса. Эндпоинт:
    -- https://api.deepseek.com/beta/completions. max_tokens = 128 и
    -- top_p = 0.9 держат ответ коротким — готовый текст приходит быстро.
    config = function()
      require("minuet").setup({
        provider = "openai_fim_compatible",
        request_timeout = 30,
        -- пауза перед запросом, чтобы не слать на каждый символ
        throttle = 800,
        debounce = 350,
        -- FIM-провайдеры шлют по запросу на каждый вариант, поэтому 1
        n_completions = 1,
        provider_options = {
          openai_fim_compatible = {
            api_key = resolve_api_key,
            end_point = "https://api.deepseek.com/beta/completions",
            model = "deepseek-flash",
            name = "Deepseek",
            optional = {
              max_tokens = 128,
              top_p = 0.9,
            },
          },
        },
        virtualtext = {
          -- где ghost-подсказки всплывают сами; в остальных ft — только
          -- вручную (next = <A-]>)
          auto_trigger_ft = {
            "lua", "python", "javascript", "javascriptreact",
            "typescript", "typescriptreact", "vue", "go", "rust",
            "css", "scss", "html",
          },
          keymap = {
            accept = "<C-y>",       -- принять всё (вместо Tab)
            accept_line = "<A-l>",  -- принять одну строку
            next = "<A-]>",         -- следующий вариант / вызвать вручную
            prev = "<A-[>",         -- предыдущий вариант
            dismiss = "<A-e>",      -- убрать подсказку
          },
        },
      })
    end,
  },
}
