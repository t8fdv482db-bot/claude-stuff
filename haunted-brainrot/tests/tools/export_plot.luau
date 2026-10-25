-- Dev tool: dumps built parts to JSON for offline previews (no Studio needed).
--   lune run tests/tools/export_plot out.json          one plot at the origin
--   lune run tests/tools/export_plot out.json world    the whole map via PlotService
local Context = require("../harness/Context")
local fs = require("@lune/fs")
local serde = require("@lune/serde")
local process = require("@lune/process")
local roblox = require("@lune/roblox")

local ctx = Context.new()
local root
if process.args[2] == "world" then
	ctx.get("ReplicatedStorage/Shared/Net").Server.Init()
	ctx.get("ServerScriptService/Services/PlotService").Init()
	root = ctx.game:GetService("Workspace"):FindFirstChild("Map")
else
	local MansionBuilder = ctx.get("ServerScriptService/Lib/MansionBuilder")
	root = roblox.Instance.new("Folder")
	MansionBuilder.BuildPlot(1, roblox.CFrame.new(), root)
end

local out = {}
for _, d in root:GetDescendants() do
	if d:IsA("BasePart") then
		local x, y, z, r00, r01, r02, r10, r11, r12, r20, r21, r22 = d.CFrame:GetComponents()
		table.insert(out, {
			name = d.Name,
			cls = d.ClassName,
			size = { d.Size.X, d.Size.Y, d.Size.Z },
			cf = { x, y, z, r00, r01, r02, r10, r11, r12, r20, r21, r22 },
			color = { d.Color.R, d.Color.G, d.Color.B },
			t = d.Transparency,
			mat = tostring(d.Material),
		})
	end
end
fs.writeFile(process.args[1], serde.encode("json", out))
print(`{#out} parts`)
