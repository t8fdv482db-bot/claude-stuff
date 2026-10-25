--!strict
--[[
	DataService
	Owns every player's saved data for the session.

	* Loads with a session lock (Lib/SessionStore) when a player joins; kicks with a friendly
	  message if data can't be loaded safely (never plays on a blank save that would overwrite).
	* Autosaves every GameConfig.Data.autosaveSeconds, saves + releases on leave and on shutdown.
	* In Studio without "Enable Studio Access to API Services", falls back to an in-memory store.

	Other services:
	  DataService.Get(player)            -> PlayerData? (nil until loaded)
	  DataService.WaitForData(player)    -> PlayerData? (yields until loaded or player leaves)
	  DataService.Loaded:Connect(fn(player, data))
	  DataService.Releasing:Connect(fn(player, data))  -- last chance to write before the final save
]]

local DataStoreService = game:GetService("DataStoreService")
local Players = game:GetService("Players")
local ReplicatedStorage = game:GetService("ReplicatedStorage")
local RunService = game:GetService("RunService")

local Shared = ReplicatedStorage.Shared
local GameConfig = require(Shared.Config.GameConfig)
local Net = require(Shared.Net)
local Signal = require(Shared.Util.Signal)

local Lib = script.Parent.Parent.Lib
local DataMigrations = require(Lib.DataMigrations)
local DataTemplate = require(Lib.DataTemplate)
local SessionStore = require(Lib.SessionStore)

export type PlayerData = DataTemplate.PlayerData

local DataService = {
	Loaded = Signal.new() :: Signal.Signal<Player, PlayerData>,
	Releasing = Signal.new() :: Signal.Signal<Player, PlayerData>,
	UsingMemoryStore = false,
}

local store: any = nil
local sessions: { [Player]: any } = {}
local joinedAt: { [Player]: number } = {}

local KICK_LOAD_FAILED = "👻 The ghosts couldn't load your save right now. Nothing was lost - please rejoin in a moment!"
local KICK_LOCKED = "👻 Your save is still being used by another server. Please wait a few seconds and rejoin!"
local KICK_LOST = "👻 You joined this game somewhere else, so this server let go of your save."

-- In-memory DataStore with UpdateAsync semantics (Studio without API access).
local function memoryStore()
	local data: { [string]: any } = {}
	return {
		UpdateAsync = function(_, key: string, fn: (any, any) -> any)
			local new = fn(DataMigrations.DeepCopy(data[key]), nil)
			if new ~= nil then
				data[key] = DataMigrations.DeepCopy(new)
			end
			return data[key], nil
		end,
	}
end

local function pickDataStore(): any
	local ok, result = pcall(function()
		local ds = DataStoreService:GetDataStore(GameConfig.Data.storeName, GameConfig.Data.storeScope)
		if RunService:IsStudio() then
			-- Probe: throws if Studio API access is disabled.
			ds:UpdateAsync("__probe", function(old)
				return old
			end)
		end
		return ds
	end)
	if ok then
		return result
	end
	if RunService:IsStudio() then
		warn("[DataService] DataStores unavailable in Studio (enable API access to test saving). Using an in-memory store.")
		DataService.UsingMemoryStore = true
		return memoryStore()
	end
	error(`[DataService] Could not open DataStore: {result}`)
end

function DataService.Get(player: Player): PlayerData?
	local s = sessions[player]
	return if s then s.Data else nil
end

function DataService.WaitForData(player: Player, timeout: number?): PlayerData?
	local deadline = os.clock() + (timeout or 60)
	while not sessions[player] and player.Parent ~= nil and os.clock() < deadline do
		task.wait(0.1)
	end
	return DataService.Get(player)
end

function DataService.IsLoaded(player: Player): boolean
	return sessions[player] ~= nil
end

local function key(player: Player): string
	return `Player_{player.UserId}`
end

local function accumulatePlaytime(player: Player)
	local data = DataService.Get(player)
	local since = joinedAt[player]
	if data and since then
		local whole = math.floor(os.clock() - since)
		data.stats.playSeconds += whole
		joinedAt[player] = since + whole -- keep the fractional remainder for next time
	end
end

local function onPlayerAdded(player: Player)
	local session, reason = store:Load(key(player))
	if not session then
		warn(`[DataService] load failed for {player.Name}: {reason}`)
		player:Kick(if reason == "locked" then KICK_LOCKED else KICK_LOAD_FAILED)
		return
	end
	if player.Parent == nil then
		-- Left while we were loading: let go straight away.
		session:Release()
		return
	end
	session.OnLost = function()
		sessions[player] = nil
		player:Kick(KICK_LOST)
	end
	local data = session.Data
	data.lastJoin = os.time()
	sessions[player] = session
	joinedAt[player] = os.clock()
	player:SetAttribute("DataLoaded", true)
	DataService.Loaded:Fire(player, data)
end

local function onPlayerRemoving(player: Player)
	local session = sessions[player]
	if not session then
		return
	end
	accumulatePlaytime(player)
	DataService.Releasing:Fire(player, session.Data)
	sessions[player] = nil
	joinedAt[player] = nil
	session:Release()
end

-- ------------------------------------------------------------------ settings remote
local SETTING_VALIDATORS: { [string]: (any) -> boolean } = {
	musicVolume = function(v)
		return type(v) == "number" and v == v and v >= 0 and v <= 1
	end,
	sfxVolume = function(v)
		return type(v) == "number" and v == v and v >= 0 and v <= 1
	end,
	lowGraphics = function(v)
		return type(v) == "boolean"
	end,
	reducedMotion = function(v)
		return type(v) == "boolean"
	end,
	peacefulBase = function(v)
		return type(v) == "boolean"
	end,
}

-- Hook so gameplay services can veto a setting change (e.g. Peaceful Base while carrying a brainrot).
DataService.SettingGuards = {} :: { [string]: (Player, any) -> (boolean, string?) }
DataService.SettingChanged = Signal.new() :: Signal.Signal<Player, string, any>

function DataService.ApplySetting(player: Player, settingKey: string, value: any): (boolean, string?)
	local data = DataService.Get(player)
	local validator = SETTING_VALIDATORS[settingKey]
	if not data or not validator or not validator(value) then
		return false, "invalid"
	end
	local guard = DataService.SettingGuards[settingKey]
	if guard then
		local ok, reason = guard(player, value)
		if not ok then
			return false, reason
		end
	end
	;(data.settings :: any)[settingKey] = value
	player:SetAttribute(`Setting_{settingKey}`, value)
	DataService.SettingChanged:Fire(player, settingKey, value)
	return true
end

-- Read-only snapshot for the client UI (no receipts or internal bookkeeping).
function DataService.ClientSnapshot(player: Player): { [string]: any }?
	local data = DataService.Get(player)
	if not data then
		return nil
	end
	return {
		settings = DataMigrations.DeepCopy(data.settings),
		upgrades = DataMigrations.DeepCopy(data.upgrades),
		defenses = DataMigrations.DeepCopy(data.defenses),
		index = DataMigrations.DeepCopy(data.index),
		stats = DataMigrations.DeepCopy(data.stats),
		floorsUnlocked = data.floorsUnlocked,
		tutorialComplete = data.tutorialComplete,
		cosmetics = DataMigrations.DeepCopy(data.cosmetics),
	}
end

-- ------------------------------------------------------------------ lifecycle
function DataService.Init()
	local cfg = GameConfig.Data
	store = SessionStore.new({
		store = pickDataStore(),
		jobId = if game.JobId ~= "" then game.JobId else "studio",
		clock = os.time,
		wait = function(s)
			task.wait(s)
		end,
		prepare = DataMigrations.Prepare,
		lockStaleSeconds = cfg.lockStaleSeconds,
		retries = cfg.loadRetries,
		retryBaseDelay = cfg.retryBaseDelaySeconds,
		lockedRetryDelay = cfg.lockedRetryDelaySeconds,
		maxLockedAttempts = cfg.maxLockedAttempts,
		log = function(msg)
			warn(`[SessionStore] {msg}`)
		end,
	})

	Net.Server.On("UpdateSetting", function(player, settingKey, value)
		local ok, reason = DataService.ApplySetting(player, settingKey, value)
		if not ok and reason and reason ~= "invalid" then
			Net.Server.Fire("Notify", player, reason, "Error")
		end
	end)
	Net.Server.OnInvoke("GetPlayerData", function(player)
		return DataService.ClientSnapshot(player)
	end)
end

function DataService.Start()
	Players.PlayerAdded:Connect(function(player)
		task.spawn(onPlayerAdded, player)
	end)
	Players.PlayerRemoving:Connect(onPlayerRemoving)
	for _, player in Players:GetPlayers() do
		task.spawn(onPlayerAdded, player)
	end

	task.spawn(function()
		while true do
			task.wait(GameConfig.Data.autosaveSeconds)
			DataService.SaveAll()
		end
	end)

	game:BindToClose(function()
		DataService.Shutdown()
	end)
end

-- Saves everyone without releasing (autosave).
function DataService.SaveAll()
	for player, session in sessions do
		accumulatePlaytime(player)
		task.spawn(function()
			session:Save()
		end)
	end
end

-- Final save + release for every player (server shutdown).
function DataService.Shutdown()
	for player, session in sessions do
		accumulatePlaytime(player)
		DataService.Releasing:Fire(player, session.Data)
	end
	table.clear(sessions)
	store:SaveAll(true, GameConfig.Data.shutdownTimeoutSeconds)
end

return DataService
