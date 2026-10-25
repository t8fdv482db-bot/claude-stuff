--!strict
--[[
	UpgradeConfig
	Player upgrades, mansion floors, rebirth tiers, defenses and the gate lock.
	Costs follow cost(level) = floor(baseCost * costGrowth ^ level) for the NEXT level.
]]

export type Currency = "Ectoplasm" | "Candy" | "SoulGems"

export type UpgradeDef = {
	id: string,
	displayName: string,
	description: string,
	currency: Currency,
	maxLevel: number,
	baseCost: number,
	costGrowth: number,
	baseValue: number, -- value at level 0
	valuePerLevel: number, -- added per level
	unit: string, -- shown in UI ("studs/s", "s", "%")
}

export type DefenseDef = {
	id: string,
	displayName: string,
	description: string,
	currency: Currency,
	maxLevel: number,
	costs: { number }, -- cost to reach level i (costs[1] buys level 1)
	-- per-level stats; index = level
	stats: { { [string]: number } },
}

export type RebirthDef = {
	rebirth: number, -- the rebirth number this tier grants (1-based)
	ectoplasmRequired: number,
	brainrotsRequired: number, -- placed brainrots needed
	incomeMultiplier: number, -- permanent total multiplier after this rebirth
	soulGems: number,
	unlockFloor: number?, -- mansion floor unlocked by this rebirth
	aura: string, -- aura cosmetic id
	title: string,
}

export type FloorDef = {
	floor: number,
	displayName: string,
	pedestals: number,
	unlock: "Start" | "Upgrade" | "Rebirth",
	rebirthRequired: number?,
	upgradeCost: number?, -- Ectoplasm (only for unlock == "Upgrade")
}

local UpgradeConfig = {}

UpgradeConfig.StartingEctoplasm = 100

-- ---------------------------------------------------------------- player upgrades
UpgradeConfig.Upgrades = {
	WalkSpeed = {
		id = "WalkSpeed",
		displayName = "Spooky Sprint",
		description = "Run faster everywhere.",
		currency = "Ectoplasm",
		maxLevel = 10,
		baseCost = 400,
		costGrowth = 1.85,
		baseValue = 16,
		valuePerLevel = 1,
		unit = "speed",
	},
	StealSpeed = {
		id = "StealSpeed",
		displayName = "Sticky Fingers",
		description = "Grab brainrots faster (shorter hold time).",
		currency = "Ectoplasm",
		maxLevel = 8,
		baseCost = 750,
		costGrowth = 2,
		baseValue = 1, -- multiplier on hold time
		valuePerLevel = -0.06,
		unit = "x hold",
	},
	CarrySpeed = {
		id = "CarrySpeed",
		displayName = "Ghost Legs",
		description = "Lose less speed while carrying a brainrot.",
		currency = "Ectoplasm",
		maxLevel = 8,
		baseCost = 900,
		costGrowth = 2,
		baseValue = 0, -- added to the rarity carry multiplier (capped at 1)
		valuePerLevel = 0.03,
		unit = "+speed",
	},
	GateDuration = {
		id = "GateDuration",
		displayName = "Stronger Barrier",
		description = "Your ghost gate stays up longer.",
		currency = "Ectoplasm",
		maxLevel = 6,
		baseCost = 1500,
		costGrowth = 2.2,
		baseValue = 60,
		valuePerLevel = 4, -- max 84s, always shorter than the 90s cooldown
		unit = "s",
	},
} :: { [string]: UpgradeDef }

function UpgradeConfig.UpgradeCost(id: string, currentLevel: number): number?
	local u = UpgradeConfig.Upgrades[id]
	if not u or currentLevel >= u.maxLevel then
		return nil
	end
	return math.floor(u.baseCost * u.costGrowth ^ currentLevel)
end

function UpgradeConfig.UpgradeValue(id: string, level: number): number
	local u = UpgradeConfig.Upgrades[id]
	assert(u, `Unknown upgrade {id}`)
	return u.baseValue + u.valuePerLevel * math.clamp(level, 0, u.maxLevel)
end

-- ---------------------------------------------------------------- mansion floors
UpgradeConfig.Floors = {
	{ floor = 1, displayName = "Creaky Ground Floor", pedestals = 8, unlock = "Start" },
	{ floor = 2, displayName = "Portrait Hall", pedestals = 8, unlock = "Upgrade", upgradeCost = 25000 },
	{ floor = 3, displayName = "Rooftop Pumpkin Garden", pedestals = 4, unlock = "Rebirth", rebirthRequired = 1 },
	{ floor = 4, displayName = "Crypt Basement", pedestals = 6, unlock = "Rebirth", rebirthRequired = 3 },
	{ floor = 5, displayName = "Sky Attic", pedestals = 8, unlock = "Rebirth", rebirthRequired = 5 },
} :: { FloorDef }

-- Extra pedestals from the "Extra Pedestals" game pass (added to Floor 1's row).
UpgradeConfig.GamePassExtraPedestals = 4

-- ---------------------------------------------------------------- rebirths
-- stylua: ignore
UpgradeConfig.Rebirths = {
	{ rebirth = 1,  ectoplasmRequired = 1e6,   brainrotsRequired = 8,  incomeMultiplier = 1.5, soulGems = 5,   unlockFloor = 3, aura = "WispTrail",       title = "Ghost Apprentice" },
	{ rebirth = 2,  ectoplasmRequired = 4e6,   brainrotsRequired = 10, incomeMultiplier = 2,   soulGems = 8,   aura = "CandyHalo",       title = "Spooky Collector" },
	{ rebirth = 3,  ectoplasmRequired = 1.5e7, brainrotsRequired = 12, incomeMultiplier = 3,   soulGems = 12,  unlockFloor = 4, aura = "BatSwarm",        title = "Crypt Keeper" },
	{ rebirth = 4,  ectoplasmRequired = 5e7,   brainrotsRequired = 14, incomeMultiplier = 4,   soulGems = 18,  aura = "PumpkinGlow",     title = "Pumpkin Baron" },
	{ rebirth = 5,  ectoplasmRequired = 1.5e8, brainrotsRequired = 16, incomeMultiplier = 6,   soulGems = 25,  unlockFloor = 5, aura = "MoonbeamCrown",   title = "Phantom Royal" },
	{ rebirth = 6,  ectoplasmRequired = 5e8,   brainrotsRequired = 18, incomeMultiplier = 8,   soulGems = 35,  aura = "SpectralFlames",  title = "Wraith Lord" },
	{ rebirth = 7,  ectoplasmRequired = 1.5e9, brainrotsRequired = 20, incomeMultiplier = 11,  soulGems = 50,  aura = "RainbowGoo",      title = "Ectoplasm Tycoon" },
	{ rebirth = 8,  ectoplasmRequired = 5e9,   brainrotsRequired = 22, incomeMultiplier = 15,  soulGems = 70,  aura = "GhostChoir",      title = "Haunt Master" },
	{ rebirth = 9,  ectoplasmRequired = 1.5e10,brainrotsRequired = 24, incomeMultiplier = 20,  soulGems = 100, aura = "StarlightSheet",  title = "Midnight Monarch" },
	{ rebirth = 10, ectoplasmRequired = 5e10,  brainrotsRequired = 26, incomeMultiplier = 30,  soulGems = 150, aura = "MoonEaterGlow",   title = "Legend of the Moon" },
} :: { RebirthDef }

function UpgradeConfig.RebirthMultiplier(rebirths: number): number
	if rebirths <= 0 then
		return 1
	end
	local tier = UpgradeConfig.Rebirths[math.min(rebirths, #UpgradeConfig.Rebirths)]
	return tier.incomeMultiplier
end

function UpgradeConfig.NextRebirth(rebirths: number): RebirthDef?
	return UpgradeConfig.Rebirths[rebirths + 1]
end

-- ---------------------------------------------------------------- defenses
-- stylua: ignore
UpgradeConfig.Defenses = {
	SlimeFloor = {
		id = "SlimeFloor", displayName = "Slime Floor", currency = "Ectoplasm", maxLevel = 4,
		description = "Gooey green slime by your door that slows thieves.",
		costs = { 2000, 8000, 30000, 120000 },
		stats = { { slowMultiplier = 0.7 }, { slowMultiplier = 0.6 }, { slowMultiplier = 0.5 }, { slowMultiplier = 0.45 } },
	},
	JackInTheCoffin = {
		id = "JackInTheCoffin", displayName = "Jack-in-the-Coffin", currency = "Ectoplasm", maxLevel = 3,
		description = "Springs up and boings thieves back to your entrance.",
		costs = { 6000, 25000, 100000 },
		stats = { { cooldown = 12 }, { cooldown = 9 }, { cooldown = 6 } },
	},
	GhostGuard = {
		id = "GhostGuard", displayName = "Ghost Guard", currency = "Candy", maxLevel = 3,
		description = "A friendly ghost that patrols your mansion and tags thieves.",
		costs = { 50, 150, 400 },
		stats = { { patrolSpeed = 10, tagRange = 6 }, { patrolSpeed = 13, tagRange = 7 }, { patrolSpeed = 16, tagRange = 8 } },
	},
	LaserCobwebs = {
		id = "LaserCobwebs", displayName = "Laser Cobwebs", currency = "Ectoplasm", maxLevel = 3,
		description = "Sweeping web beams; touching one makes a thief drop their brainrot.",
		costs = { 15000, 60000, 240000 },
		stats = { { sweepSeconds = 4, beams = 1 }, { sweepSeconds = 3.5, beams = 2 }, { sweepSeconds = 3, beams = 3 } },
	},
	PumpkinCannon = {
		id = "PumpkinCannon", displayName = "Pumpkin Cannon", currency = "Candy", maxLevel = 3,
		description = "Fires soft pumpkins that bonk thieves backwards. No damage, just bonk.",
		costs = { 80, 250, 600 },
		stats = { { fireInterval = 4, knockback = 40 }, { fireInterval = 3, knockback = 50 }, { fireInterval = 2.2, knockback = 60 } },
	},
} :: { [string]: DefenseDef }

-- ---------------------------------------------------------------- gate lock
UpgradeConfig.Gate = {
	baseDurationSeconds = 60, -- extended by the GateDuration upgrade
	cooldownSeconds = 90, -- measured from when the barrier was raised
}

return UpgradeConfig
