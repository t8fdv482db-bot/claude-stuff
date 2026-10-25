--!nocheck
-- Verifies the Rojo-built place: `rojo build -o build/HauntedBrainrot.rbxlx && lune run tests/verify_build`
local fs = require("@lune/fs")
local process = require("@lune/process")
local roblox = require("@lune/roblox")

local place = roblox.deserializePlace(fs.readFile("build/HauntedBrainrot.rbxlx"))
local problems = {}
local function expectPath(path, className)
	local node = place
	for _, part in string.split(path, "/") do
		node = if node == place then place:GetService(part) else node:FindFirstChild(part)
		if not node then
			table.insert(problems, `missing {path}`)
			return
		end
	end
	if className and node.ClassName ~= className then
		table.insert(problems, `{path} is {node.ClassName}, expected {className}`)
	end
end

for _, line in string.split(fs.readFile("tests/expected_tree.txt"), "\n") do
	local path, cls = line:match("^(%S+)%s+(%S+)$")
	if path then
		expectPath(path, cls)
	end
end
if place:GetService("Workspace").StreamingEnabled ~= true then
	table.insert(problems, "Workspace.StreamingEnabled should be true")
end
if #problems > 0 then
	for _, p in problems do
		print("✗ " .. p)
	end
	process.exit(1)
end
print("✓ build/HauntedBrainrot.rbxlx has the expected structure")
