-- Gaming / latency related render settings (NVIDIA RTX 5080)

hl.config({
	render = {
		-- 2 = only for fullscreen windows tagged as game content.
		-- Hands the game's buffer straight to the display, bypassing composition.
		direct_scanout = 2,
	},
	cursor = {
		-- 0 = do NOT disable hardware cursors. Software cursors force a full
		-- recomposite on every cursor move, which kills direct scanout.
		no_hardware_cursors = 0,
	},
	-- Uncomment for tearing (lowest latency, but gives up VRR smoothness).
	-- Also add `immediate = true` to the game window rule in windowrules.lua.
	-- general = { allow_tearing = true },
})
