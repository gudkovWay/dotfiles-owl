-- Keep every monitor at non-negative coordinates: XWayland cannot represent a
-- negative layout and repacks the outputs side by side, which makes Wine/UE5
-- games pick the wrong monitor size. DP-2 stays above DP-3, same as before.
hl.monitor({
	output = "DP-2",
	mode = "3440x1440@180",
	position = "0x0",
	scale = "1",
})
hl.monitor({
	output = "DP-3",
	mode = "2560x1440@240",
	position = "0x1440",
	scale = "1",
})

-- Левый рельс Noctalia (`bar.mina-left`, thickness = 104) резервирует 104 px
-- на каждом мониторе, поэтому отступ окна слева = 104 + gaps_out, а справа —
-- только gaps_out. Чтобы окно не липло к правому краю, правый отступ получает
-- ту же суммарную ширину, что и левый: gaps_out задан по сторонам (CssGap).
local LEFT_RAIL = 104

hl.workspace_rule({
	workspace = "m[DP-3]",
	gaps_in = 0,
	gaps_out = { top = 0, right = LEFT_RAIL, bottom = 0, left = 0 },
})
hl.workspace_rule({
	workspace = "m[DP-2]",
	gaps_in = 0,
	gaps_out = { top = 0, right = LEFT_RAIL, bottom = 0, left = 0 },
})
