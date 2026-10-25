--!strict
--[[
	GameConfig
	World layout, conveyor, stealing rules, safety limits and data settings.
	Balancing for brainrots/rarities/upgrades/events lives in the sibling config modules.
]]

local GameConfig = {}

-- ---------------------------------------------------------------- world / plots
GameConfig.Plots = {
	count = 8, -- one per player; also the server's MaxPlayers
	ringRadius = 170, -- studs from the plaza centre to each plot centre
	plotSize = Vector3.new(64, 1, 72), -- footprint (X width, Z depth)
	plazaRadius = 105, -- the central carnival plaza
	groundY = 0,
	floorHeight = 14, -- height of one mansion storey
	claimZoneSize = Vector3.new(14, 8, 10), -- in front of the door; thieves claim here
}

-- ---------------------------------------------------------------- conveyor
GameConfig.Conveyor = {
	beltSpeed = 6, -- studs/s
	spawnIntervalSeconds = 2.4,
	maxItemsOnBelt = 26,
	buyRange = 14, -- max distance between player and item to buy
	poolSize = 32, -- pooled models per brainrot type is capped by this total
}

-- ---------------------------------------------------------------- income
GameConfig.Income = {
	tickSeconds = 1, -- how often income is paid
	offlineEarnings = false, -- no offline income: brainrots only earn while you're here
	peacefulBaseMultiplier = 0.8, -- Peaceful Base players earn 80%
}

-- ---------------------------------------------------------------- stealing & protection
GameConfig.Steal = {
	carryTimeoutSeconds = 45, -- dropped and returned home after this long
	restealProtectionSeconds = 30, -- a freshly stolen brainrot can't be stolen again for this long
	newPlayerProtectionSeconds = 180, -- base can't be stolen from right after joining
	maxStealsPerVictimWindow = 3, -- anti-harassment: same thief -> same victim
	victimWindowSeconds = 5 * 60,
	promptMaxDistance = 10,
	tagRange = 7, -- owner touches thief within this range to tag
}

-- ---------------------------------------------------------------- data
GameConfig.Data = {
	storeName = "HauntedBrainrot_PlayerData",
	storeScope = "v1",
	autosaveSeconds = 60,
	lockStaleSeconds = 600, -- a session lock older than this (no heartbeat) can be taken over
	loadRetries = 5,
	retryBaseDelaySeconds = 1.5, -- exponential backoff base
	lockedRetryDelaySeconds = 4, -- wait between attempts when another server still holds the lock
	maxLockedAttempts = 6,
	shutdownTimeoutSeconds = 25,
}

-- ---------------------------------------------------------------- remotes / anti-exploit
GameConfig.Net = {
	defaultRateLimit = 10, -- calls per second per player per remote (unless overridden)
}

-- ---------------------------------------------------------------- rewards
GameConfig.Rewards = {
	ferrisWheelTopEctoplasm = 50, -- multiplied by rebirth multiplier
	ferrisWheelCooldownSeconds = 300,
}

return GameConfig
