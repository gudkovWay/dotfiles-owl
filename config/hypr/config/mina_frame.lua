local M = {}
local target = "*"
local root = "/home/q/.local/lib/kitty-skins/mina-sacrifice-r2/pack"

function M.apply()
    if hl.plugin.sacrifice == nil then return end
    if _G.__mina_frame_rule == nil then
        _G.__mina_frame_rule = hl.window_rule({
            name = "sacrifice-application-frame",
            match = {class = ".*"},
            border_size = 0,
            rounding = 0,
        })
    end
    hl.config({plugin = {sacrifice = {root = root, target = target, enabled = 1, reduced_motion = 0}}})
    hl.dispatch(hl.plugin.sacrifice.reload())
end

return M
