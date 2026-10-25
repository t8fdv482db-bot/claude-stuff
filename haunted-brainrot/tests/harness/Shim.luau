--!nocheck
--[[
	Shim: adds the Roblox engine behaviour Lune's DOM doesn't have, so real Instances can be used
	in tests: events (Touched, Triggered, OnServerEvent, CharacterAdded...), Kick, WaitForChild,
	Model:PivotTo/GetPivot, Destroy tracking. Installed once per process.
]]

local roblox = require("@lune/roblox")
local Mocks = require("./Mocks")

local Shim = {}
local installed = false

local side = setmetatable({}, { __mode = "k" })
local function state(inst)
	local s = side[inst]
	if not s then
		s = { signals = {} }
		side[inst] = s
	end
	return s
end
Shim.state = state

local function signalProp(className, name)
	roblox.implementProperty(className, name, function(self)
		local s = state(self)
		s.signals[name] = s.signals[name] or Mocks.signal()
		return s.signals[name]
	end)
end

function Shim.install()
	if installed then
		return
	end
	installed = true

	roblox.implementMethod("Instance", "WaitForChild", function(self, name, timeout)
		local c = self:FindFirstChild(name)
		if not c and timeout == nil then
			error(`Infinite yield possible on WaitForChild({name}) in {self.Name}`)
		end
		return c
	end)
	roblox.implementMethod("Instance", "GetAttributeChangedSignal", function(self, attr)
		local s = state(self)
		local key = "Attr:" .. attr
		s.signals[key] = s.signals[key] or Mocks.signal()
		return s.signals[key]
	end)
	signalProp("Instance", "Destroying")

	-- Players
	roblox.implementMethod("Player", "Kick", function(self, msg)
		state(self).kicked = msg or ""
	end)
	signalProp("Player", "CharacterAdded")
	signalProp("Player", "CharacterRemoving")
	roblox.implementMethod("Player", "LoadCharacter", function(self)
		local char = roblox.Instance.new("Model")
		char.Name = self.Name
		local root = roblox.Instance.new("Part")
		root.Name = "HumanoidRootPart"
		root.Parent = char
		local hum = roblox.Instance.new("Humanoid")
		hum.Parent = char
		char.PrimaryPart = root
		self.Character = char
		self.CharacterAdded:Fire(char)
		return char
	end)

	-- Parts / models
	signalProp("BasePart", "Touched")
	signalProp("BasePart", "TouchEnded")
	roblox.implementMethod("Model", "GetPivot", function(self)
		if self.PrimaryPart then
			return self.PrimaryPart.CFrame
		end
		for _, d in self:GetDescendants() do
			if d:IsA("BasePart") then
				return d.CFrame
			end
		end
		return roblox.CFrame.new()
	end)
	roblox.implementMethod("Model", "PivotTo", function(self, target)
		local current = self:GetPivot()
		local delta = target * current:Inverse()
		for _, d in self:GetDescendants() do
			if d:IsA("BasePart") then
				d.CFrame = delta * d.CFrame
			end
		end
	end)

	-- Interaction / networking
	signalProp("ProximityPrompt", "Triggered")
	signalProp("ProximityPrompt", "PromptButtonHoldBegan")
	signalProp("ProximityPrompt", "PromptButtonHoldEnded")
	signalProp("ClickDetector", "MouseClick")
	signalProp("RemoteEvent", "OnServerEvent")
	signalProp("RemoteEvent", "OnClientEvent")
	roblox.implementMethod("RemoteEvent", "FireClient", function(self, player, ...)
		local s = state(self)
		s.sent = s.sent or {}
		table.insert(s.sent, { player = player, args = table.pack(...) })
	end)
	roblox.implementMethod("RemoteEvent", "FireAllClients", function(self, ...)
		local s = state(self)
		s.sent = s.sent or {}
		table.insert(s.sent, { player = "all", args = table.pack(...) })
	end)
	roblox.implementProperty("RemoteFunction", "OnServerInvoke", function(self)
		return state(self).invoke
	end, function(self, fn)
		state(self).invoke = fn
	end)
end

-- Test helpers -------------------------------------------------------------------------------

function Shim.kicked(player)
	return state(player).kicked
end

function Shim.sent(remote)
	return state(remote).sent or {}
end

-- Simulate a client firing a RemoteEvent.
function Shim.clientFire(remote, player, ...)
	remote.OnServerEvent:Fire(player, ...)
end

function Shim.clientInvoke(remote, player, ...)
	local fn = state(remote).invoke
	assert(fn, `{remote.Name} has no OnServerInvoke`)
	return fn(player, ...)
end

return Shim
