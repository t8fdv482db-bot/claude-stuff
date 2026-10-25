--!strict
--[[
	DataMigrations
	Upgrades old saves to DataTemplate.VERSION and fills in any missing keys.

	To change the save format:
	  1. bump DataTemplate.VERSION
	  2. add Migrations[oldVersion] = function(data, now) ... return data end
	Migrations run in order, one version at a time, before Reconcile.
]]

local DataTemplate = require(script.Parent.DataTemplate)

local DataMigrations = {}

-- Migrations[n] upgrades a version-n save to version n+1.
local Migrations: { [number]: (any, number) -> any } = {
	-- v0 = pre-release saves that stored only { Ectoplasm = n, Brainrots = { {id=...} } }
	[0] = function(old, now)
		local data = DataTemplate.new(now)
		if type(old.Ectoplasm) == "number" then
			data.currencies.Ectoplasm = old.Ectoplasm
		end
		if type(old.Brainrots) == "table" then
			for _, b in old.Brainrots do
				if type(b) == "table" and type(b.id) == "string" then
					local uid = tostring(data.nextBrainrotUid)
					data.nextBrainrotUid += 1
					data.brainrots[uid] = { id = b.id, mutation = b.mutation, pedestal = nil, acquiredAt = now }
				end
			end
		end
		data.version = 1
		return data
	end,
}
DataMigrations.Migrations = Migrations

local function deepCopy<T>(value: T): T
	if type(value) ~= "table" then
		return value
	end
	local out = {}
	for k, v in value :: any do
		out[k] = deepCopy(v)
	end
	return out :: any
end
DataMigrations.DeepCopy = deepCopy

-- Adds keys present in `template` but missing (or wrong-typed) in `data`, recursively.
-- Map-like tables that are meant to hold dynamic keys (brainrots, index, ...) are left alone
-- beyond their own existence.
local DYNAMIC = {
	brainrots = true,
	index = true,
	indexRewardsClaimed = true,
	achievements = true,
	receipts = true,
	defenses = true,
	auras = true,
	list = true,
}

local function reconcile(data: { [any]: any }, template: { [any]: any })
	for key, tv in template do
		local dv = data[key]
		if dv == nil or type(dv) ~= type(tv) then
			data[key] = deepCopy(tv)
		elseif type(tv) == "table" and not DYNAMIC[key] then
			reconcile(dv, tv)
		end
	end
end

function DataMigrations.Reconcile(data: any, now: number): DataTemplate.PlayerData
	reconcile(data, DataTemplate.new(now))
	return data
end

-- Full pipeline for a freshly loaded value (nil for brand-new players).
function DataMigrations.Prepare(raw: any, now: number): DataTemplate.PlayerData
	if raw == nil or type(raw) ~= "table" then
		return DataTemplate.new(now)
	end
	local data = raw
	local version = if type(data.version) == "number" then data.version else 0
	if version > DataTemplate.VERSION then
		-- Saved by a newer server build: keep it untouched (never downgrade or lose fields).
		return data
	end
	while version < DataTemplate.VERSION do
		local step = Migrations[version]
		assert(step, `No migration from data version {version}`)
		data = step(data, now)
		version += 1
		data.version = version
	end
	return DataMigrations.Reconcile(data, now)
end

return DataMigrations
