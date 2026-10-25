--!strict
--[[
	DataTemplate
	The shape of a player's saved data (current version). New keys added here are filled into
	existing saves automatically by DataMigrations.Reconcile; renames/reshapes need a migration.
]]

local UpgradeConfig = require(game:GetService("ReplicatedStorage").Shared.Config.UpgradeConfig)

export type OwnedBrainrot = {
	id: string, -- BrainrotConfig id
	mutation: string?, -- BrainrotConfig mutation id
	pedestal: number?, -- pedestal index in the mansion (nil = in storage)
	acquiredAt: number, -- os.time()
	stolen: boolean?, -- true if obtained by stealing
}

export type PlayerData = {
	version: number,
	currencies: { Ectoplasm: number, Candy: number, SoulGems: number },
	stats: {
		totalEctoplasm: number, -- lifetime earned (leaderboard)
		brainrotsStolen: number, -- successful steals (leaderboard)
		timesStolenFrom: number,
		raidsDefended: number, -- (leaderboard)
		brainrotsBought: number,
		rebirths: number,
		playSeconds: number,
	},
	brainrots: { [string]: OwnedBrainrot }, -- keyed by unique id
	nextBrainrotUid: number,
	upgrades: { [string]: number }, -- UpgradeConfig.Upgrades id -> level
	floorsUnlocked: number,
	defenses: { [string]: number }, -- UpgradeConfig.Defenses id -> level
	index: { [string]: { discoveredAt: number, mutations: { [string]: boolean } } },
	indexRewardsClaimed: { [string]: boolean },
	quests: { day: number, list: { any } },
	achievements: { [string]: number }, -- id -> unlocked os.time()
	cosmetics: { equippedAura: string?, auras: { [string]: boolean }, title: string? },
	settings: {
		musicVolume: number,
		sfxVolume: number,
		lowGraphics: boolean,
		reducedMotion: boolean,
		peacefulBase: boolean,
	},
	tutorialComplete: boolean,
	receipts: { [string]: number }, -- processed developer product PurchaseIds (idempotency)
	firstJoin: number,
	lastJoin: number,
}

local DataTemplate = {}

DataTemplate.VERSION = 1

function DataTemplate.new(now: number): PlayerData
	local upgrades = {}
	for id in UpgradeConfig.Upgrades do
		upgrades[id] = 0
	end
	return {
		version = DataTemplate.VERSION,
		currencies = { Ectoplasm = UpgradeConfig.StartingEctoplasm, Candy = 0, SoulGems = 0 },
		stats = {
			totalEctoplasm = 0,
			brainrotsStolen = 0,
			timesStolenFrom = 0,
			raidsDefended = 0,
			brainrotsBought = 0,
			rebirths = 0,
			playSeconds = 0,
		},
		brainrots = {},
		nextBrainrotUid = 1,
		upgrades = upgrades,
		floorsUnlocked = 1,
		defenses = {},
		index = {},
		indexRewardsClaimed = {},
		quests = { day = 0, list = {} },
		achievements = {},
		cosmetics = { equippedAura = nil, auras = {}, title = nil },
		settings = {
			musicVolume = 0.6,
			sfxVolume = 0.8,
			lowGraphics = false,
			reducedMotion = false,
			peacefulBase = false,
		},
		tutorialComplete = false,
		receipts = {},
		firstJoin = now,
		lastJoin = now,
	}
end

return DataTemplate
