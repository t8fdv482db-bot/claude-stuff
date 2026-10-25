--!strict
--[[
	RarityConfig
	Every rarity tier: conveyor odds, colours, steal/carry tuning and presentation.
	Weights are percentages and must sum to 100 (validated by ConfigValidator).
]]

export type RarityName = "Common" | "Uncommon" | "Rare" | "Epic" | "Legendary" | "Mythic" | "Secret"

export type RarityDef = {
	name: RarityName,
	order: number, -- 1 = most common; used for sorting and "X or better" checks
	weight: number, -- conveyor odds in percent
	color: Color3, -- PointLight / UI colour
	glowBrightness: number, -- PointLight brightness
	stealHoldSeconds: number, -- ProximityPrompt hold time to steal
	carrySpeedMultiplier: number, -- thief WalkSpeed multiplier while carrying
	announce: boolean, -- server-wide announcement when it appears on the conveyor
	playOrgan: boolean, -- haunted organ jingle when it appears
	eventOnly: string?, -- only spawns while this EventConfig event is active
}

local RarityConfig = {}

RarityConfig.Order = { "Common", "Uncommon", "Rare", "Epic", "Legendary", "Mythic", "Secret" } :: { RarityName }

RarityConfig.Tiers = {
	Common = {
		name = "Common",
		order = 1,
		weight = 55,
		color = Color3.fromRGB(190, 200, 210),
		glowBrightness = 0.6,
		stealHoldSeconds = 1,
		carrySpeedMultiplier = 0.95,
		announce = false,
		playOrgan = false,
	},
	Uncommon = {
		name = "Uncommon",
		order = 2,
		weight = 25,
		color = Color3.fromRGB(110, 230, 120),
		glowBrightness = 0.8,
		stealHoldSeconds = 1.5,
		carrySpeedMultiplier = 0.9,
		announce = false,
		playOrgan = false,
	},
	Rare = {
		name = "Rare",
		order = 3,
		weight = 12,
		color = Color3.fromRGB(80, 170, 255),
		glowBrightness = 1,
		stealHoldSeconds = 2,
		carrySpeedMultiplier = 0.85,
		announce = false,
		playOrgan = false,
	},
	Epic = {
		name = "Epic",
		order = 4,
		weight = 5,
		color = Color3.fromRGB(185, 90, 255),
		glowBrightness = 1.3,
		stealHoldSeconds = 2.5,
		carrySpeedMultiplier = 0.8,
		announce = false,
		playOrgan = false,
	},
	Legendary = {
		name = "Legendary",
		order = 5,
		weight = 2.5,
		color = Color3.fromRGB(255, 190, 40),
		glowBrightness = 1.6,
		stealHoldSeconds = 3,
		carrySpeedMultiplier = 0.75,
		announce = true,
		playOrgan = true,
	},
	Mythic = {
		name = "Mythic",
		order = 6,
		weight = 0.45,
		color = Color3.fromRGB(255, 70, 120),
		glowBrightness = 2,
		stealHoldSeconds = 4,
		carrySpeedMultiplier = 0.7,
		announce = true,
		playOrgan = true,
	},
	Secret = {
		name = "Secret",
		order = 7,
		weight = 0.05,
		color = Color3.fromRGB(255, 120, 30),
		glowBrightness = 2.5,
		stealHoldSeconds = 4,
		carrySpeedMultiplier = 0.65,
		announce = true,
		playOrgan = true,
		eventOnly = "BloodOrangeMoon",
	},
} :: { [RarityName]: RarityDef }

function RarityConfig.Get(name: RarityName): RarityDef
	local def = RarityConfig.Tiers[name]
	assert(def, `Unknown rarity {name}`)
	return def
end

-- True if `name` is at least as rare as `threshold` (e.g. AtLeast("Mythic", "Legendary") == true).
function RarityConfig.AtLeast(name: RarityName, threshold: RarityName): boolean
	return RarityConfig.Get(name).order >= RarityConfig.Get(threshold).order
end

return RarityConfig
