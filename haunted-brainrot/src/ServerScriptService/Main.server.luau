--!strict
--[[
	Server bootstrap. Initialises every service in dependency order, then starts them.
	Init(): create remotes/state, no yielding.   Start(): connect events, begin loops.
]]

local ReplicatedStorage = game:GetService("ReplicatedStorage")

local Shared = ReplicatedStorage.Shared
local ConfigValidator = require(Shared.Config.ConfigValidator)
local Net = require(Shared.Net)

local Services = script.Parent.Services

-- Order matters: a service may only depend on services listed before it.
local ORDER = {
	"DataService",
	"EconomyService",
	"PlotService",
}

local problems = ConfigValidator.Validate()
for _, p in problems do
	warn(`[Config] {p}`)
end
if #problems > 0 then
	warn(`[Config] {#problems} config problem(s) found - fix the Config modules!`)
end

Net.Server.Init()

local loaded = {}
for _, name in ORDER do
	local module = Services:FindFirstChild(name)
	assert(module, `Missing service {name}`)
	local service = require(module) :: any
	if service.Init then
		service.Init()
	end
	table.insert(loaded, { name = name, service = service })
end

for _, entry in loaded do
	if entry.service.Start then
		local ok, err = pcall(entry.service.Start)
		if not ok then
			warn(`[Main] {entry.name}.Start failed: {err}`)
		end
	end
end

print(`[Main] Steal a Haunted Brainrot server ready ({#loaded} services)`)
