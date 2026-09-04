
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

-- Bigger outer gaps only on monitor DP-2 (m[...] selector matches that monitor's workspaces)
hl.workspace_rule({ workspace = "m[DP-2]", gaps_out = 150 })
