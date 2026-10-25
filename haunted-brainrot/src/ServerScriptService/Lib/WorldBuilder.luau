--!strict
--[[
	WorldBuilder
	The static ground of the map: graveyard grass, the round plaza in the middle, cobblestone
	paths from the plaza to every plot gate, and a neutral SpawnLocation in the plaza (players are
	moved to their own mansion as soon as their plot is assigned).
	The carnival attractions on the plaza (conveyor, clock tower, ferris wheel...) are built by
	their own services in later phases under Workspace.Map.Plaza.
]]

local ReplicatedStorage = game:GetService("ReplicatedStorage")

local GameConfig = require(ReplicatedStorage.Shared.Config.GameConfig)
local PlotLayout = require(script.Parent.PlotLayout)

local WorldBuilder = {}

local function part(parent: Instance, name: string, size: Vector3, cf: CFrame, color: Color3, material: Enum.Material, shape: Enum.PartType?): Part
	local p = Instance.new("Part")
	p.Name = name
	p.Anchored = true
	p.Size = size
	p.CFrame = cf
	p.Color = color
	p.Material = material
	p.TopSurface = Enum.SurfaceType.Smooth
	p.BottomSurface = Enum.SurfaceType.Smooth
	if shape then
		p.Shape = shape
	end
	p.Parent = parent
	return p
end

function WorldBuilder.Build(workspaceRoot: Instance): Folder
	local cfg = GameConfig.Plots
	local map = Instance.new("Folder")
	map.Name = "Map"

	local ground = Instance.new("Folder")
	ground.Name = "Ground"
	ground.Parent = map
	local extent = (cfg.ringRadius + cfg.plotSize.Z) * 2 + 200
	part(ground, "Graveyard", Vector3.new(extent, 2, extent), CFrame.new(0, cfg.groundY - 1, 0), Color3.fromRGB(48, 60, 54), Enum.Material.Grass)

	local plaza = Instance.new("Folder")
	plaza.Name = "Plaza"
	plaza.Parent = map
	local disc = part(
		plaza,
		"PlazaFloor",
		Vector3.new(0.6, cfg.plazaRadius * 2, cfg.plazaRadius * 2),
		CFrame.new(0, cfg.groundY + 0.3, 0) * CFrame.Angles(0, 0, math.rad(90)),
		Color3.fromRGB(90, 70, 120),
		Enum.Material.Cobblestone,
		Enum.PartType.Cylinder
	)
	disc.Name = "PlazaFloor"
	part(
		plaza,
		"PlazaRing",
		Vector3.new(0.7, cfg.plazaRadius * 2 + 4, cfg.plazaRadius * 2 + 4),
		CFrame.new(0, cfg.groundY + 0.25, 0) * CFrame.Angles(0, 0, math.rad(90)),
		Color3.fromRGB(110, 255, 120),
		Enum.Material.Neon,
		Enum.PartType.Cylinder
	).CanCollide = false

	-- Paths from the plaza edge to each plot's gate.
	local paths = Instance.new("Folder")
	paths.Name = "Paths"
	paths.Parent = map
	for i, plotCF in PlotLayout.All() do
		local gate = plotCF * CFrame.new(0, 0, -cfg.plotSize.Z / 2)
		local from = Vector3.new(gate.Position.X, cfg.groundY, gate.Position.Z)
		local to = PlotLayout.Center + (from - PlotLayout.Center).Unit * (cfg.plazaRadius - 2)
		local length = (from - to).Magnitude
		local mid = (from + to) / 2
		part(
			paths,
			`Path_{i}`,
			Vector3.new(10, 0.4, length),
			CFrame.lookAt(mid + Vector3.new(0, 0.2, 0), to + Vector3.new(0, 0.2, 0)),
			Color3.fromRGB(120, 105, 130),
			Enum.Material.Cobblestone
		)
	end

	local spawn = Instance.new("SpawnLocation")
	spawn.Name = "PlazaSpawn"
	spawn.Anchored = true
	spawn.Neutral = true
	spawn.Size = Vector3.new(12, 1, 12)
	spawn.CFrame = CFrame.new(0, cfg.groundY + 0.6, 0)
	spawn.Transparency = 1
	spawn.CanCollide = false
	spawn.Duration = 0 -- no forcefield bubble
	spawn.Parent = map

	map.Parent = workspaceRoot
	return map
end

return WorldBuilder
