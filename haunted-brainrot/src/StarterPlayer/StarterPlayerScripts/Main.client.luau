--!strict
--[[
	Client bootstrap. Requires every controller in ./Controllers, calls Init() on all of them,
	then Start(). Controllers only handle presentation and input; the server owns all game state.
]]

local Controllers = script.Parent:WaitForChild("Controllers")

-- Load order for controllers that depend on each other; any others load afterwards alphabetically.
local ORDER = { "UIController", "PlotController" }

local modules: { { name: string, controller: any } } = {}
local seen: { [string]: boolean } = {}

local function load(module: Instance)
	if seen[module.Name] or not module:IsA("ModuleScript") then
		return
	end
	seen[module.Name] = true
	local ok, controller = pcall(require, module)
	if ok then
		table.insert(modules, { name = module.Name, controller = controller })
	else
		warn(`[Client] failed to load {module.Name}: {controller}`)
	end
end

for _, name in ORDER do
	local m = Controllers:WaitForChild(name, 10)
	if m then
		load(m)
	end
end
local rest = Controllers:GetChildren()
table.sort(rest, function(a, b)
	return a.Name < b.Name
end)
for _, m in rest do
	load(m)
end

for _, entry in modules do
	if entry.controller.Init then
		local ok, err = pcall(entry.controller.Init)
		if not ok then
			warn(`[Client] {entry.name}.Init failed: {err}`)
		end
	end
end
for _, entry in modules do
	if entry.controller.Start then
		task.spawn(function()
			local ok, err = pcall(entry.controller.Start)
			if not ok then
				warn(`[Client] {entry.name}.Start failed: {err}`)
			end
		end)
	end
end
