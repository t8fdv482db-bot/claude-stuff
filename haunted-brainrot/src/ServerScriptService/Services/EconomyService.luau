--!strict
--[[
	EconomyService
	The only code that changes currency balances. Server-authoritative.

	* Balances live in saved data; mirrored to player attributes ("Ectoplasm", "Candy", "SoulGems")
	  so the client HUD can animate them without any remote traffic.
	* Ectoplasm earned also counts toward stats.totalEctoplasm (leaderboard).
	* Income multipliers are composed from registered providers (rebirth, Peaceful Base, and later
	  game passes / events), so every system multiplies income the same way.
]]

local ReplicatedStorage = game:GetService("ReplicatedStorage")

local Shared = ReplicatedStorage.Shared
local Format = require(Shared.Util.Format)
local GameConfig = require(Shared.Config.GameConfig)
local Signal = require(Shared.Util.Signal)
local UpgradeConfig = require(Shared.Config.UpgradeConfig)

local DataService = require(script.Parent.DataService)

export type Currency = "Ectoplasm" | "Candy" | "SoulGems"

local CURRENCIES: { Currency } = { "Ectoplasm", "Candy", "SoulGems" }

local EconomyService = {
	-- (player, currency, newBalance, delta, reason)
	Changed = Signal.new() :: Signal.Signal<Player, Currency, number, number, string>,
}

local multiplierProviders: { [string]: (Player) -> number } = {}

local function isCurrency(c: any): boolean
	return table.find(CURRENCIES, c) ~= nil
end

local function validAmount(n: any): boolean
	return type(n) == "number" and n == n and n >= 0 and n < math.huge
end

local function publish(player: Player, currency: Currency, balance: number, delta: number, reason: string)
	player:SetAttribute(currency, balance)
	if currency == "Ectoplasm" then
		local stats = player:FindFirstChild("leaderstats")
		local value = stats and stats:FindFirstChild("Ectoplasm")
		if value then
			(value :: StringValue).Value = Format.Abbreviate(balance)
		end
	end
	EconomyService.Changed:Fire(player, currency, balance, delta, reason)
end

function EconomyService.Get(player: Player, currency: Currency): number
	local data = DataService.Get(player)
	return if data then data.currencies[currency] else 0
end

-- Adds currency. Returns false if the player's data isn't loaded or the amount is invalid.
function EconomyService.Add(player: Player, currency: Currency, amount: number, reason: string?): boolean
	local data = DataService.Get(player)
	if not data or not isCurrency(currency) or not validAmount(amount) then
		return false
	end
	if amount == 0 then
		return true
	end
	data.currencies[currency] += amount
	if currency == "Ectoplasm" then
		data.stats.totalEctoplasm += amount
	end
	publish(player, currency, data.currencies[currency], amount, reason or "")
	return true
end

-- Spends currency atomically: either the full amount is deducted or nothing happens.
function EconomyService.TrySpend(player: Player, currency: Currency, amount: number, reason: string?): boolean
	local data = DataService.Get(player)
	if not data or not isCurrency(currency) or not validAmount(amount) then
		return false
	end
	if data.currencies[currency] < amount then
		return false
	end
	data.currencies[currency] -= amount
	publish(player, currency, data.currencies[currency], -amount, reason or "")
	return true
end

function EconomyService.CanAfford(player: Player, currency: Currency, amount: number): boolean
	return validAmount(amount) and EconomyService.Get(player, currency) >= amount
end

-- Sets a balance directly (rebirth reset, admin tools). Does not count toward lifetime totals.
function EconomyService.Set(player: Player, currency: Currency, amount: number, reason: string?): boolean
	local data = DataService.Get(player)
	if not data or not isCurrency(currency) or not validAmount(amount) then
		return false
	end
	local delta = amount - data.currencies[currency]
	data.currencies[currency] = amount
	publish(player, currency, amount, delta, reason or "set")
	return true
end

-- ------------------------------------------------------------------ income multipliers
function EconomyService.RegisterMultiplier(name: string, provider: (Player) -> number)
	multiplierProviders[name] = provider
end

function EconomyService.GetIncomeMultiplier(player: Player): number
	local total = 1
	for name, provider in multiplierProviders do
		local ok, m = pcall(provider, player)
		if ok and type(m) == "number" and m == m and m > 0 then
			total *= m
		elseif not ok then
			warn(`[EconomyService] multiplier {name} errored: {m}`)
		end
	end
	return total
end

-- ------------------------------------------------------------------ lifecycle
local function setupPlayer(player: Player, data: DataService.PlayerData)
	local leaderstats = Instance.new("Folder")
	leaderstats.Name = "leaderstats"
	local ecto = Instance.new("StringValue")
	ecto.Name = "Ectoplasm"
	ecto.Value = Format.Abbreviate(data.currencies.Ectoplasm)
	ecto.Parent = leaderstats
	local rebirths = Instance.new("IntValue")
	rebirths.Name = "Rebirths"
	rebirths.Value = data.stats.rebirths
	rebirths.Parent = leaderstats
	leaderstats.Parent = player
	for _, c in CURRENCIES do
		player:SetAttribute(c, data.currencies[c])
	end
	player:SetAttribute("Rebirths", data.stats.rebirths)
	player:SetAttribute("IncomeMultiplier", EconomyService.GetIncomeMultiplier(player))
end

function EconomyService.Init()
	EconomyService.RegisterMultiplier("Rebirth", function(player)
		local data = DataService.Get(player)
		return if data then UpgradeConfig.RebirthMultiplier(data.stats.rebirths) else 1
	end)
	EconomyService.RegisterMultiplier("PeacefulBase", function(player)
		local data = DataService.Get(player)
		return if data and data.settings.peacefulBase then GameConfig.Income.peacefulBaseMultiplier else 1
	end)
end

function EconomyService.Start()
	DataService.Loaded:Connect(setupPlayer)
	DataService.SettingChanged:Connect(function(player, settingKey)
		if settingKey == "peacefulBase" then
			player:SetAttribute("IncomeMultiplier", EconomyService.GetIncomeMultiplier(player))
		end
	end)
end

return EconomyService
