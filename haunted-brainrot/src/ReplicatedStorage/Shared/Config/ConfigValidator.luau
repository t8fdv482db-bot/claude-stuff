--!strict
--[[
	ConfigValidator
	Sanity-checks every balancing table. Runs on server start (problems are logged loudly)
	and in the test suite, so a bad edit to a config module is caught immediately.
]]

local Config = script.Parent
local RarityConfig = require(Config.RarityConfig)
local BrainrotConfig = require(Config.BrainrotConfig)
local UpgradeConfig = require(Config.UpgradeConfig)
local EventConfig = require(Config.EventConfig)
local GameConfig = require(Config.GameConfig)

local ConfigValidator = {}

function ConfigValidator.Validate(): { string }
	local problems: { string } = {}
	local function check(cond: boolean, msg: string)
		if not cond then
			table.insert(problems, msg)
		end
	end

	-- Rarities
	local total = 0
	local lastOrder = 0
	for i, name in RarityConfig.Order do
		local tier = RarityConfig.Tiers[name]
		check(tier ~= nil, `Rarity {name} listed in Order but not defined`)
		if tier then
			total += tier.weight
			check(tier.order == i, `Rarity {name} has order {tier.order}, expected {i}`)
			check(tier.order > lastOrder, `Rarity {name} out of order`)
			lastOrder = tier.order
			check(tier.stealHoldSeconds > 0, `Rarity {name} stealHoldSeconds must be > 0`)
			check(tier.carrySpeedMultiplier > 0 and tier.carrySpeedMultiplier <= 1, `Rarity {name} carry multiplier out of range`)
			if tier.eventOnly then
				check(EventConfig.Events[tier.eventOnly :: any] ~= nil, `Rarity {name} references unknown event {tier.eventOnly}`)
			end
		end
	end
	check(math.abs(total - 100) < 1e-6, `Rarity weights sum to {total}, expected 100`)

	-- Brainrots
	local seen = {}
	for _, b in BrainrotConfig.Roster do
		check(not seen[b.id], `Duplicate brainrot id {b.id}`)
		seen[b.id] = true
		check(RarityConfig.Tiers[b.rarity] ~= nil, `Brainrot {b.id} has unknown rarity {b.rarity}`)
		check(b.incomePerSecond > 0, `Brainrot {b.id} must earn something`)
		check(b.price > 0, `Brainrot {b.id} needs a price`)
		check(#b.voiceLine > 0 and #b.voiceLine <= 60, `Brainrot {b.id} voice line must be 1-60 chars`)
		check(#b.displayName <= 30, `Brainrot {b.id} name too long for the billboard`)
	end
	for _, name in RarityConfig.Order do
		check(#BrainrotConfig.GetByRarity(name) > 0, `No brainrots of rarity {name}`)
	end
	-- Rarer tiers should always earn more than the best of the tier below.
	for i = 2, #RarityConfig.Order do
		local lowerBest, upperWorst = 0, math.huge
		for _, b in BrainrotConfig.GetByRarity(RarityConfig.Order[i - 1]) do
			lowerBest = math.max(lowerBest, b.incomePerSecond)
		end
		for _, b in BrainrotConfig.GetByRarity(RarityConfig.Order[i]) do
			upperWorst = math.min(upperWorst, b.incomePerSecond)
		end
		check(upperWorst > lowerBest, `{RarityConfig.Order[i]} income should exceed {RarityConfig.Order[i - 1]}`)
	end

	-- Mutations
	local mutationChance = 0
	for _, m in BrainrotConfig.Mutations do
		mutationChance += m.chance
		check(m.incomeMultiplier > 1, `Mutation {m.id} should boost income`)
	end
	check(mutationChance < 25, `Mutations total {mutationChance}% - they should stay rare`)

	-- Upgrades
	for id, u in UpgradeConfig.Upgrades do
		check(u.id == id, `Upgrade key {id} doesn't match id {u.id}`)
		check(u.maxLevel >= 1 and u.baseCost > 0 and u.costGrowth > 1, `Upgrade {id} has invalid costs`)
	end
	check(UpgradeConfig.UpgradeValue("StealSpeed", UpgradeConfig.Upgrades.StealSpeed.maxLevel) > 0.3, "StealSpeed max must keep hold time positive")
	local maxGate = UpgradeConfig.UpgradeValue("GateDuration", UpgradeConfig.Upgrades.GateDuration.maxLevel)
	check(maxGate < UpgradeConfig.Gate.cooldownSeconds, "Gate duration must stay below its cooldown")

	-- Floors
	for i, f in UpgradeConfig.Floors do
		check(f.floor == i, `Floor entry {i} has floor {f.floor}`)
		if f.unlock == "Rebirth" then
			check(f.rebirthRequired ~= nil, `Floor {i} needs rebirthRequired`)
		elseif f.unlock == "Upgrade" then
			check(f.upgradeCost ~= nil, `Floor {i} needs upgradeCost`)
		end
	end

	-- Rebirths: strictly increasing requirements and multipliers
	for i, r in UpgradeConfig.Rebirths do
		check(r.rebirth == i, `Rebirth entry {i} numbered {r.rebirth}`)
		if i > 1 then
			local prev = UpgradeConfig.Rebirths[i - 1]
			check(r.ectoplasmRequired > prev.ectoplasmRequired, `Rebirth {i} requirement must increase`)
			check(r.incomeMultiplier > prev.incomeMultiplier, `Rebirth {i} multiplier must increase`)
		end
		if r.unlockFloor then
			local floor = UpgradeConfig.Floors[r.unlockFloor]
			check(floor ~= nil and floor.rebirthRequired == r.rebirth, `Rebirth {i} floor unlock mismatch`)
		end
	end

	-- Defenses
	for id, d in UpgradeConfig.Defenses do
		check(#d.costs == d.maxLevel and #d.stats == d.maxLevel, `Defense {id} needs one cost and stat row per level`)
	end

	-- Events
	check(EventConfig.DayCycle.lengthSeconds > 0, "Day length must be positive")
	for i = 2, #EventConfig.Phases do
		check(EventConfig.Phases[i].startHour > EventConfig.Phases[i - 1].startHour, "Phases must be in clock order")
	end
	local raidHours = EventConfig.Raid.durationSeconds / EventConfig.SecondsPerHour
	check(EventConfig.PhaseAt(EventConfig.Raid.startHour + raidHours).name == "Night", "Raid must end before dawn")
	for _, wave in EventConfig.Raid.waves do
		check(wave.atSecond < EventConfig.Raid.durationSeconds, "Raid wave starts after the raid ends")
	end
	for id, e in EventConfig.Events do
		check(e.id == id, `Event key {id} doesn't match id {e.id}`)
		check(e.durationSeconds > 0 and e.durationSeconds < EventConfig.Rotation.intervalSeconds, `Event {id} duration invalid`)
	end
	check(EventConfig.Events.GhostDisco.params.lightCycleSeconds >= 1, "Ghost Disco lights must not change faster than 1/s")

	-- World
	local p = GameConfig.Plots
	local spacing = 2 * p.ringRadius * math.sin(math.pi / p.count)
	check(spacing > p.plotSize.X + 10, `Plots overlap: spacing {spacing} vs width {p.plotSize.X}`)
	check(p.ringRadius - p.plotSize.Z / 2 > p.plazaRadius, "Plots intrude into the plaza")

	return problems
end

return ConfigValidator
