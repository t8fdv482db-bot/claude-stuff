--!strict
--[[
	Net
	Single source of truth for every RemoteEvent / RemoteFunction.

	* Server: Net.Server.Init() creates ReplicatedStorage/Remotes with one instance per definition.
	* Server handlers registered with Net.Server.On / OnInvoke are wrapped with:
	    - argument validation against the definition's schema (types, ranges, NaN/inf, lengths, enums)
	    - per-player token-bucket rate limiting
	    - pcall so one bad call can't break the handler
	* Client: Net.Client.Fire / Invoke / On.

	Remote direction is enforced: clients can only call "ClientToServer" remotes.
]]

local Players = game:GetService("Players")
local ReplicatedStorage = game:GetService("ReplicatedStorage")
local RunService = game:GetService("RunService")

local GameConfig = require(script.Parent.Config.GameConfig)
local RateLimiter = require(script.Parent.Util.RateLimiter)

export type ArgSpec = string | {
	type: string,
	optional: boolean?,
	min: number?,
	max: number?,
	maxLength: number?,
	oneOf: { any }?,
}

export type RemoteDef = {
	kind: "Event" | "Function",
	direction: "ClientToServer" | "ServerToClient",
	args: { ArgSpec }?, -- schema for client->server arguments
	rateLimit: number?, -- calls per second per player
}

local Net = {}

-- Every remote in the game. Later phases append here; names are what appears in ReplicatedStorage/Remotes.
Net.Definitions = {
	-- server -> client
	Notify = { kind = "Event", direction = "ServerToClient" }, -- (text: string, style: string)
	-- client -> server
	UpdateSetting = {
		kind = "Event",
		direction = "ClientToServer",
		args = {
			{ type = "string", oneOf = { "musicVolume", "sfxVolume", "lowGraphics", "reducedMotion", "peacefulBase" } },
			"any", -- value type depends on the key; validated by the handler
		},
		rateLimit = 4,
	},
	GetPlayerData = { kind = "Function", direction = "ClientToServer", args = {}, rateLimit = 2 },
} :: { [string]: RemoteDef }

-- ---------------------------------------------------------------- validation (pure, unit-tested)
local function checkOne(value: any, spec: ArgSpec): (boolean, string?)
	local s = if type(spec) == "string" then { type = spec } else spec
	local t = s.type
	local optional = s.optional
	if type(t) == "string" and t:sub(-1) == "?" then
		t = t:sub(1, -2)
		optional = true
	end
	if value == nil then
		return optional == true or t == "any", "missing argument"
	end
	if t == "any" then
		return true
	end
	if t == "integer" then
		if type(value) ~= "number" or value ~= value or value % 1 ~= 0 or math.abs(value) == math.huge then
			return false, "expected integer"
		end
	elseif t == "number" then
		if type(value) ~= "number" or value ~= value or math.abs(value) == math.huge then
			return false, "expected finite number"
		end
	elseif t == "string" or t == "boolean" or t == "table" then
		if type(value) ~= t then
			return false, `expected {t}`
		end
	else
		-- Roblox types: "Vector3", "CFrame", "Instance", ...
		if typeof(value) ~= t then
			return false, `expected {t}`
		end
	end
	if s.min and value < s.min then
		return false, "below minimum"
	end
	if s.max and value > s.max then
		return false, "above maximum"
	end
	if type(value) == "string" and #value > (s.maxLength or 200) then
		return false, "string too long"
	end
	if s.oneOf and not table.find(s.oneOf, value) then
		return false, "value not allowed"
	end
	return true
end

-- Validates a full argument list against a definition. Returns ok, reason.
function Net.Validate(def: RemoteDef, args: { any }, n: number): (boolean, string?)
	local schema = def.args or {}
	if n > #schema then
		return false, "too many arguments"
	end
	for i, spec in schema do
		local ok, reason = checkOne(args[i], spec)
		if not ok then
			return false, `arg {i}: {reason}`
		end
	end
	return true
end

-- ---------------------------------------------------------------- server
local Server = {}
Net.Server = Server

local folder: Folder? = nil
local limiters: { [string]: RateLimiter.RateLimiter } = {}

local function getRemote(name: string): Instance
	local def = Net.Definitions[name]
	assert(def, `Unknown remote {name}`)
	if RunService:IsServer() then
		assert(folder, "Net.Server.Init() must run first")
		return (folder :: Folder):FindFirstChild(name) :: Instance
	end
	local remotes = ReplicatedStorage:WaitForChild("Remotes")
	return remotes:WaitForChild(name)
end

function Server.Init()
	if folder then
		return
	end
	local f = Instance.new("Folder")
	f.Name = "Remotes"
	for name, def in Net.Definitions do
		local remote = Instance.new(if def.kind == "Event" then "RemoteEvent" else "RemoteFunction")
		remote.Name = name
		remote.Parent = f
		limiters[name] = RateLimiter.new(def.rateLimit or GameConfig.Net.defaultRateLimit)
	end
	f.Parent = ReplicatedStorage
	folder = f
	Players.PlayerRemoving:Connect(function(player)
		for _, limiter in limiters do
			limiter:Forget(player)
		end
	end)
end

local function guard(name: string, def: RemoteDef, player: Player, ...: any): (boolean, string?)
	if def.direction ~= "ClientToServer" then
		return false, "wrong direction"
	end
	if not limiters[name]:Allow(player) then
		return false, "rate limited"
	end
	return Net.Validate(def, { ... }, select("#", ...))
end

-- Connect a validated handler for a client->server RemoteEvent.
function Server.On(name: string, handler: (Player, ...any) -> ())
	local def = Net.Definitions[name]
	assert(def and def.kind == "Event", `{name} is not a RemoteEvent`)
	local remote = getRemote(name) :: RemoteEvent
	remote.OnServerEvent:Connect(function(player, ...)
		local ok, reason = guard(name, def, player, ...)
		if not ok then
			warn(`[Net] rejected {name} from {player.Name}: {reason}`)
			return
		end
		local success, err = pcall(handler, player, ...)
		if not success then
			warn(`[Net] handler {name} errored: {err}`)
		end
	end)
end

-- Bind a validated handler for a client->server RemoteFunction. Rejected calls return nil.
function Server.OnInvoke(name: string, handler: (Player, ...any) -> ...any)
	local def = Net.Definitions[name]
	assert(def and def.kind == "Function", `{name} is not a RemoteFunction`)
	local remote = getRemote(name) :: RemoteFunction
	remote.OnServerInvoke = function(player, ...)
		local ok, reason = guard(name, def, player, ...)
		if not ok then
			warn(`[Net] rejected {name} from {player.Name}: {reason}`)
			return nil
		end
		local results = table.pack(pcall(handler, player, ...))
		if not results[1] then
			warn(`[Net] handler {name} errored: {results[2]}`)
			return nil
		end
		return table.unpack(results, 2, results.n)
	end
end

function Server.Fire(name: string, player: Player, ...: any)
	(getRemote(name) :: RemoteEvent):FireClient(player, ...)
end

function Server.FireAll(name: string, ...: any)
	(getRemote(name) :: RemoteEvent):FireAllClients(...)
end

-- ---------------------------------------------------------------- client
local Client = {}
Net.Client = Client

function Client.Fire(name: string, ...: any)
	(getRemote(name) :: RemoteEvent):FireServer(...)
end

function Client.Invoke(name: string, ...: any): ...any
	return (getRemote(name) :: RemoteFunction):InvokeServer(...)
end

function Client.On(name: string, handler: (...any) -> ())
	(getRemote(name) :: RemoteEvent).OnClientEvent:Connect(handler)
end

return Net
