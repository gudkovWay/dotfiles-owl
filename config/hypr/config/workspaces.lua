-- Workspace glyphs: DP-3 gets the CJK numerals 一..十, DP-2 the ten heavenly
-- stems 甲..癸. Noctalia's workspaces widget renders these as its pill labels
-- (widget.workspaces: label_source = "name"), so the bar shows kanji instead
-- of plain dots.
local NAMES_DP3 = { "一", "二", "三", "四", "五", "六", "七", "八", "九", "十" }
local NAMES_DP2 = { "甲", "乙", "丙", "丁", "戊", "己", "庚", "辛", "壬", "癸" }

for i = 1, 10 do
	hl.workspace_rule({ workspace = tostring(i), monitor = "DP-3", default = true, default_name = NAMES_DP3[i] })
end
for i = 11, 20 do
	hl.workspace_rule({ workspace = tostring(i), monitor = "DP-2", default = false, default_name = NAMES_DP2[i - 10] })
end

-- Gaming lives on workspace 4 of DP-3, so games never end up sized for the
-- ultrawide, and they run without outer gaps.
hl.workspace_rule({ workspace = "4", monitor = "DP-3", gaps_out = 0, default_name = NAMES_DP3[4] })
