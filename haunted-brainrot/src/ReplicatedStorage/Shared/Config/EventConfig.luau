--!strict
--[[
	EventConfig
	Day/night cycle, the midnight Phantom Raid, and rotating server events.
	One full day = DayCycle.lengthSeconds real seconds, mapped onto Lighting.ClockTime 0..24.
]]

export type PhaseName = "Dawn" | "Day" | "Dusk" | "Night"

export type LightingPreset = {
	ambient: Color3,
	outdoorAmbient: Color3,
	fogColor: Color3,
	fogEnd: number,
	brightness: number,
	colorShiftTop: Color3,
}

export type PhaseDef = {
	name: PhaseName,
	startHour: number, -- ClockTime at which the phase begins
	luckMultiplier: number, -- multiplies non-Common conveyor weights
	lighting: LightingPreset,
}

export type ServerEventName = "BloodOrangeMoon" | "CandyStorm" | "GravityGlitch" | "ConveyorFrenzy" | "GhostDisco"

export type ServerEventDef = {
	id: ServerEventName,
	displayName: string,
	description: string,
	durationSeconds: number,
	weight: number, -- relative pick weight in the rotation
	bannerColor: Color3,
	params: { [string]: number },
}

local EventConfig = {}

EventConfig.DayCycle = {
	lengthSeconds = 12 * 60, -- full 24h cycle in real seconds
	startHour = 8, -- ClockTime when a server boots
	lightingTweenSeconds = 6, -- smooth blend between phase presets
}

-- Seconds of real time per in-game hour (derived, do not edit).
EventConfig.SecondsPerHour = EventConfig.DayCycle.lengthSeconds / 24

-- stylua: ignore
EventConfig.Phases = {
	{
		name = "Dawn", startHour = 5, luckMultiplier = 1,
		lighting = { ambient = Color3.fromRGB(120, 100, 130), outdoorAmbient = Color3.fromRGB(170, 140, 160),
			fogColor = Color3.fromRGB(230, 170, 160), fogEnd = 700, brightness = 1.6, colorShiftTop = Color3.fromRGB(255, 190, 150) },
	},
	{
		name = "Day", startHour = 7, luckMultiplier = 1,
		lighting = { ambient = Color3.fromRGB(110, 100, 130), outdoorAmbient = Color3.fromRGB(150, 140, 170),
			fogColor = Color3.fromRGB(170, 160, 200), fogEnd = 900, brightness = 2, colorShiftTop = Color3.fromRGB(255, 240, 220) },
	},
	{
		name = "Dusk", startHour = 17, luckMultiplier = 1.15,
		lighting = { ambient = Color3.fromRGB(110, 70, 150), outdoorAmbient = Color3.fromRGB(140, 90, 180),
			fogColor = Color3.fromRGB(120, 70, 170), fogEnd = 600, brightness = 1.3, colorShiftTop = Color3.fromRGB(200, 120, 255) },
	},
	{
		name = "Night", startHour = 20, luckMultiplier = 1,
		lighting = { ambient = Color3.fromRGB(70, 60, 110), outdoorAmbient = Color3.fromRGB(80, 70, 130),
			fogColor = Color3.fromRGB(40, 30, 80), fogEnd = 450, brightness = 0.9, colorShiftTop = Color3.fromRGB(120, 140, 255) },
	},
} :: { PhaseDef }

-- Returns the phase active at a ClockTime (0..24).
function EventConfig.PhaseAt(clockTime: number): PhaseDef
	local hour = clockTime % 24
	local current = EventConfig.Phases[#EventConfig.Phases] -- Night wraps past midnight
	for _, phase in EventConfig.Phases do
		if hour >= phase.startHour then
			current = phase
		end
	end
	return current
end

-- ---------------------------------------------------------------- Phantom Raid (midnight)
EventConfig.Raid = {
	startHour = 0, -- ClockTime when the clock tower chimes
	durationSeconds = 90,
	waves = {
		{ atSecond = 0, ghostsPerBase = 2 },
		{ atSecond = 30, ghostsPerBase = 3 },
		{ atSecond = 60, ghostsPerBase = 4 },
	},
	ghostSpeed = 8, -- studs/s floating towards a pedestal
	grabSeconds = 6, -- time a prankster needs at a pedestal before floating away with it
	escapeSeconds = 10, -- time to float off-map with a brainrot; popping it returns the brainrot
	candyPerPop = 2,
	defendedBonusCandy = 25, -- if no brainrot was lost by the end of the raid
	vacuumRange = 30, -- studs
	vacuumCooldown = 0.35, -- seconds between vacuum shots
	minPlacedToBeRaided = 1, -- empty bases are skipped
}

-- ---------------------------------------------------------------- rotating server events
EventConfig.Rotation = {
	intervalSeconds = 20 * 60, -- one event roughly every 20 minutes
	jitterSeconds = 90, -- +/- random offset so servers don't sync up
	firstEventDelaySeconds = 6 * 60,
	bannerSeconds = 5,
}

-- stylua: ignore
EventConfig.Events = {
	BloodOrangeMoon = {
		id = "BloodOrangeMoon", displayName = "Blood-Orange Moon",
		description = "The moon glows orange... the secret Moon-Eater Marshmallow may appear!",
		durationSeconds = 180, weight = 1, bannerColor = Color3.fromRGB(255, 120, 30),
		params = { luckMultiplier = 1.25 },
	},
	CandyStorm = {
		id = "CandyStorm", displayName = "Candy Storm",
		description = "Candy is raining from the sky! Grab it!",
		durationSeconds = 90, weight = 3, bannerColor = Color3.fromRGB(255, 110, 200),
		params = { piecesPerSecond = 6, candyPerPiece = 1, pieceLifetime = 12 },
	},
	GravityGlitch = {
		id = "GravityGlitch", displayName = "Gravity Glitch",
		description = "Gravity went on vacation! Everything is floaty for 60 seconds.",
		durationSeconds = 60, weight = 2, bannerColor = Color3.fromRGB(120, 200, 255),
		params = { gravity = 55 }, -- default workspace gravity is 196.2
	},
	ConveyorFrenzy = {
		id = "ConveyorFrenzy", displayName = "Conveyor Frenzy",
		description = "The Spooky Conveyor runs at double speed with boosted rarities!",
		durationSeconds = 120, weight = 3, bannerColor = Color3.fromRGB(130, 255, 120),
		params = { speedMultiplier = 2, spawnRateMultiplier = 2, luckMultiplier = 1.5 },
	},
	GhostDisco = {
		id = "GhostDisco", displayName = "Ghost Disco",
		description = "Every brainrot is dancing! Bonus Ectoplasm while the disco lasts.",
		-- Light colour changes every lightCycleSeconds; kept slow (>= 1s) for photosensitivity safety.
		durationSeconds = 120, weight = 2, bannerColor = Color3.fromRGB(200, 120, 255),
		params = { incomeMultiplier = 1.25, lightCycleSeconds = 1.5 },
	},
} :: { [ServerEventName]: ServerEventDef }

return EventConfig
