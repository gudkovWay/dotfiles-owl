-- Input configuration
hl.config({
	input = {
		kb_layout = "us, ru",
		kb_variant = "",
		kb_model = "",
		kb_options = "grp:caps_toggle,fkeys:basic_13-24",
		kb_rules = "",

		-- Numpad on the Vader 5 pad must report digits, not End/Down:
		-- KP1-KP6 are how its six extra buttons reach games.
		numlock_by_default = true,
		repeat_delay = 250,
		repeat_rate = 55,

		follow_mouse = 1,

		sensitivity = 0, -- -1.0 - 1.0, 0 means no modification.

		touchpad = {
			natural_scroll = false,
		},
	},
})

hl.gesture({ fingers = 4, direction = "horizontal", action = "workspace" })
hl.gesture({ fingers = 3, direction = "down",       action = "close" })
hl.gesture({ fingers = 3, direction = "up",         action = "fullscreen" })
hl.gesture({ fingers = 3, direction = "left",       action = "float" })

-- The pad only streams its IMU in test mode, which also wakes its built-in
-- gyro-mouse. We read the IMU ourselves (scripts/gamepad-gesture.py), so the
-- cursor side of it is just noise -- turn that device off.
hl.device({ name = "flydigi-vader-5-pro", enabled = false })
