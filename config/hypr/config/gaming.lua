-- Gaming / latency related render settings (NVIDIA RTX 5080)

hl.config({
	render = {
		-- Keep fullscreen in the desktop color mode; HDR/scanout transitions
		-- blank the MSI output and interrupt its night-mode appearance.
		cm_auto_hdr = 0,
		direct_scanout = 0,
	},
	cursor = {
		-- Keep hardware cursors enabled.
		no_hardware_cursors = 0,
	},
	-- Uncomment for tearing (lowest latency, but gives up VRR smoothness).
	-- Also add `immediate = true` to the game window rule in windowrules.lua.
	-- general = { allow_tearing = true },
})
