--!nocheck
-- Mock Roblox services for unit tests: Players, RunService, DataStoreService, TextService, ...

local task = require("@lune/task")

local Mocks = {}

-- ------------------------------------------------------------------ tiny signal
local function signal()
	local s = { handlers = {} }
	function s:Connect(fn)
		local c = { Connected = true }
		function c.Disconnect()
			c.Connected = false
			local i = table.find(s.handlers, fn)
			if i then
				table.remove(s.handlers, i)
			end
		end
		table.insert(s.handlers, fn)
		return c
	end
	function s:Once(fn)
		local c
		c = s:Connect(function(...)
			c.Disconnect()
			fn(...)
		end)
		return c
	end
	function s:Fire(...)
		for _, fn in table.clone(s.handlers) do
			fn(...)
		end
	end
	function s:Wait()
		local thread = coroutine.running()
		s:Once(function(...)
			task.spawn(thread, ...)
		end)
		return coroutine.yield()
	end
	return s
end
Mocks.signal = signal

-- ------------------------------------------------------------------ players
function Mocks.Players()
	local roblox = require("@lune/roblox")
	local container = roblox.Instance.new("Folder")
	container.Name = "Players"
	local players = { list = {}, PlayerAdded = signal(), PlayerRemoving = signal(), MaxPlayers = 8, container = container }
	function players:GetPlayers()
		return table.clone(self.list)
	end
	function players:GetPlayerByUserId(id)
		for _, p in self.list do
			if p.UserId == id then
				return p
			end
		end
		return nil
	end
	function players:GetPlayerFromCharacter(char)
		for _, p in self.list do
			if p.Character == char then
				return p
			end
		end
		return nil
	end
	-- Creates a real Lune Player instance (engine behaviour comes from harness/Shim).
	function players:Join(userId, name)
		local p = roblox.Instance.new("Player")
		p.UserId = userId
		p.Name = name or `Player{userId}`
		p.DisplayName = name or `Player{userId}`
		p.Parent = container
		table.insert(self.list, p)
		self.PlayerAdded:Fire(p)
		return p
	end
	function players:Leave(p)
		self.PlayerRemoving:Fire(p)
		local i = table.find(self.list, p)
		if i then
			table.remove(self.list, i)
		end
		p.Parent = nil
	end
	return players
end

-- ------------------------------------------------------------------ run service
function Mocks.RunService(opts)
	opts = opts or {}
	return {
		Heartbeat = signal(),
		Stepped = signal(),
		IsServer = function()
			return opts.server ~= false
		end,
		IsClient = function()
			return opts.server == false
		end,
		IsStudio = function()
			return opts.studio == true
		end,
	}
end

-- ------------------------------------------------------------------ data stores
-- A shared "cloud" so several simulated servers can contend for the same keys.
function Mocks.DataStoreCloud()
	local cloud = { stores = {}, failNext = 0, calls = 0, budgetErrors = 0 }
	function cloud:Store(name, scope)
		local key = `{name}/{scope or "global"}`
		self.stores[key] = self.stores[key] or {}
		return self.stores[key]
	end
	return cloud
end

local function deepCopy(v)
	if type(v) ~= "table" then
		return v
	end
	local out = {}
	for k, x in v do
		out[k] = deepCopy(x)
	end
	return out
end
Mocks.deepCopy = deepCopy

function Mocks.DataStoreService(cloud)
	local service = {}
	function service:GetDataStore(name, scope)
		local data = cloud:Store(name, scope)
		local store = {}
		function store:UpdateAsync(key, fn)
			cloud.calls += 1
			if cloud.failNext > 0 then
				cloud.failNext -= 1
				error("502: API Services rejected request (simulated)")
			end
			-- Values are serialized like the real service: callers never share references.
			local old = deepCopy(data[key])
			local new = fn(old, nil)
			if new ~= nil then
				data[key] = deepCopy(new)
			end
			return deepCopy(data[key]), nil
		end
		function store:GetAsync(key)
			cloud.calls += 1
			return deepCopy(data[key])
		end
		function store:SetAsync(key, value)
			cloud.calls += 1
			data[key] = deepCopy(value)
		end
		return store
	end
	return service
end

-- ------------------------------------------------------------------ text filtering
function Mocks.TextService()
	return {
		FilterStringAsync = function(_, text)
			return {
				GetNonChatStringForBroadcastAsync = function()
					return (text:gsub("badword", "#######"))
				end,
			}
		end,
	}
end

return Mocks
