--!strict
--[[
	MansionBuilder
	Builds a player's plot procedurally from Parts: lot, picket fence, front gate, Floor 1 of the
	haunted mansion (creaky porch, glowing windows, 8 pedestals), owner sign, spawn point and the
	claim zone used by stealing.

	Coordinates are written in plot-local space (see PlotLayout): origin = plot centre at ground
	level, -Z = towards the plaza (front), +Y = up. Every Part is anchored.

	Named children other systems rely on:
	  Plot_<i>                  Model, attributes PlotIndex, OwnerUserId, OwnerName
	    Pedestals/Pedestal_<n>  Model, attributes Index, Floor; child Part "Top" has Attachment "BrainrotAnchor"
	    SpawnPoint              invisible Part; players spawn here facing the plaza
	    ClaimZone               invisible Part at the front door; carried brainrots are claimed here
	    OwnerSign/Board         Part with SurfaceGuis "SignFront"/"SignBack" (TextLabels "Title", "Income")
	    Mansion/Floor1          the storey; later floors are added beside it by BuildFloor
	    Mansion/Roof            sits on top of the highest floor
	    FrontGate               gate posts/doors (Gate lock barrier is added by the stealing phase)
]]

local ReplicatedStorage = game:GetService("ReplicatedStorage")

local GameConfig = require(ReplicatedStorage.Shared.Config.GameConfig)
local Theme = require(ReplicatedStorage.Shared.Theme)

local MansionBuilder = {}

local PLOT = GameConfig.Plots
local FLOOR_H = PLOT.floorHeight

-- Mansion footprint inside the plot (local space).
MansionBuilder.Mansion = {
	width = 44, -- X
	depth = 36, -- Z
	centerZ = 8, -- pushed back so there's a front yard
	wall = 1.2,
	foundation = 1.5,
	doorWidth = 10,
	doorHeight = 9.5,
}
local M = MansionBuilder.Mansion
local FRONT_Z = M.centerZ - M.depth / 2 -- front wall plane (-10)

-- Palette: spooky-cute, readable from far away.
local C = {
	Grass = Color3.fromRGB(58, 74, 62),
	Path = Color3.fromRGB(120, 105, 130),
	Stone = Color3.fromRGB(95, 90, 110),
	StoneDark = Color3.fromRGB(65, 60, 80),
	Wall = Color3.fromRGB(105, 70, 150),
	WallTrim = Color3.fromRGB(70, 45, 105),
	Wood = Color3.fromRGB(110, 80, 60),
	WoodDark = Color3.fromRGB(80, 55, 45),
	Roof = Color3.fromRGB(45, 35, 70),
	Fence = Color3.fromRGB(220, 215, 235),
	Window = Color3.fromRGB(255, 190, 80),
	Pumpkin = Color3.fromRGB(255, 140, 30),
	Stem = Color3.fromRGB(70, 110, 50),
	Ecto = Theme.Colors.Ecto,
	SignBoard = Color3.fromRGB(40, 25, 60),
}

type Builder = {
	root: CFrame,
	part: (parent: Instance, name: string, size: Vector3, at: CFrame, color: Color3, material: Enum.Material?, shape: Enum.PartType?) -> Part,
}

local function newBuilder(root: CFrame): Builder
	local b = {} :: Builder
	b.root = root
	function b.part(parent, name, size, at, color, material, shape)
		local p = Instance.new("Part")
		p.Name = name
		p.Anchored = true
		p.Size = size
		p.CFrame = root * at
		p.Color = color
		p.Material = material or Enum.Material.SmoothPlastic
		p.TopSurface = Enum.SurfaceType.Smooth
		p.BottomSurface = Enum.SurfaceType.Smooth
		if shape then
			p.Shape = shape
		end
		p.Parent = parent
		return p
	end
	return b
end

local function folder(name: string, parent: Instance): Folder
	local f = Instance.new("Folder")
	f.Name = name
	f.Parent = parent
	return f
end

local function model(name: string, parent: Instance): Model
	local m = Instance.new("Model")
	m.Name = name
	m.Parent = parent
	return m
end

-- Vertical cylinder centred at (x, y, z) local.
local function upright(x: number, y: number, z: number): CFrame
	return CFrame.new(x, y, z) * CFrame.Angles(0, 0, math.rad(90))
end

local function light(parent: Instance, color: Color3, range: number, brightness: number)
	local l = Instance.new("PointLight")
	l.Color = color
	l.Range = range
	l.Brightness = brightness
	l.Shadows = false
	l.Parent = parent
end

local function decorate(p: Part)
	p.CanCollide = false
	p.CanQuery = false
	p.CanTouch = false
	p.CastShadow = false
end

-- ------------------------------------------------------------------ pieces

local function buildLot(b: Builder, plot: Model)
	local lot = folder("Lot", plot)
	b.part(lot, "Ground", Vector3.new(PLOT.plotSize.X, 1, PLOT.plotSize.Z), CFrame.new(0, -0.35, 0), C.Grass, Enum.Material.Grass)
	-- Stone path from the gate to the porch.
	local gateZ = -PLOT.plotSize.Z / 2
	local porchZ = FRONT_Z - 9
	local pathLength = porchZ - gateZ
	b.part(lot, "Path", Vector3.new(8, 0.3, pathLength), CFrame.new(0, 0.2, gateZ + pathLength / 2), C.Path, Enum.Material.Cobblestone)

	-- Picket fence around the lot with an opening for the gate at the front.
	local fence = folder("Fence", lot)
	local hx, hz = PLOT.plotSize.X / 2 - 0.5, PLOT.plotSize.Z / 2 - 0.5
	local gap = 7 -- half-width of the gate opening
	local function run(from: Vector3, to: Vector3)
		local delta = to - from
		local length = delta.Magnitude
		local mid = (from + to) / 2
		local cf = CFrame.lookAt(mid, mid + delta.Unit)
		local rail = b.part(fence, "Rail", Vector3.new(0.4, 0.4, length), cf * CFrame.new(0, 2.2, 0), C.Fence)
		rail.CastShadow = false
		local posts = math.max(2, math.floor(length / 2.5))
		for i = 0, posts do
			local p = from + delta * (i / posts)
			local picket = b.part(fence, "Picket", Vector3.new(0.6, 3.2, 0.6), CFrame.new(p.X, 1.6, p.Z), C.Fence)
			picket.CastShadow = false
		end
	end
	run(Vector3.new(-hx, 0, -hz), Vector3.new(-gap, 0, -hz))
	run(Vector3.new(gap, 0, -hz), Vector3.new(hx, 0, -hz))
	run(Vector3.new(-hx, 0, -hz), Vector3.new(-hx, 0, hz))
	run(Vector3.new(hx, 0, -hz), Vector3.new(hx, 0, hz))
	run(Vector3.new(-hx, 0, hz), Vector3.new(hx, 0, hz))

	-- Gravestones and a twisty dead tree in the front yard.
	local yard = folder("Yard", lot)
	for i, x in { -22, -16, 17 } do
		local z = -26 + (i % 2) * 4
		local stone = b.part(yard, "Gravestone", Vector3.new(3, 3.6, 0.8), CFrame.new(x, 1.8, z) * CFrame.Angles(0, 0, math.rad((i - 2) * 6)), C.Stone, Enum.Material.Slate)
		stone:SetAttribute("Interactive", "Gravestone") -- client pops a cartoon ghost when walked past
		b.part(yard, "GravestoneTop", Vector3.new(0.8, 3, 3), upright(x, 3.6, z) * CFrame.Angles(0, math.rad(90), 0), C.Stone, Enum.Material.Slate, Enum.PartType.Cylinder)
	end
	local tree = model("DeadTree", yard)
	local trunkAt = Vector3.new(22, 0, -18)
	b.part(tree, "Trunk", Vector3.new(1.6, 10, 1.6), CFrame.new(trunkAt.X, 5, trunkAt.Z) * CFrame.Angles(0, 0, math.rad(4)), C.WoodDark, Enum.Material.Wood)
	for i, branch in { { -40, 6.5 }, { 35, 8 }, { -20, 9.5 } } do
		local angle, height = branch[1], branch[2]
		b.part(tree, `Branch{i}`, Vector3.new(0.7, 4.5, 0.7), CFrame.new(trunkAt.X, height, trunkAt.Z) * CFrame.Angles(math.rad(i * 25), 0, math.rad(angle)) * CFrame.new(0, 2, 0), C.WoodDark, Enum.Material.Wood)
	end
end

local function buildGate(b: Builder, plot: Model)
	local gate = model("FrontGate", plot)
	local z = -PLOT.plotSize.Z / 2 + 0.5
	for _, x in { -7.5, 7.5 } do
		b.part(gate, "Pillar", Vector3.new(2.4, 6, 2.4), CFrame.new(x, 3, z), C.StoneDark, Enum.Material.Cobblestone)
		local pumpkin = b.part(gate, "PillarPumpkin", Vector3.new(2.2, 1.8, 2.2), CFrame.new(x, 6.9, z), C.Pumpkin, Enum.Material.SmoothPlastic, Enum.PartType.Ball)
		decorate(pumpkin)
		light(pumpkin, C.Pumpkin, 12, 1.2)
	end
	-- Swung-open wooden doors (the gate lock barrier is a separate glowing wall added later).
	for _, side in { -1, 1 } do
		local hinge = CFrame.new(side * 6.2, 2.6, z) * CFrame.Angles(0, math.rad(side * 70), 0)
		local door = b.part(gate, "Door", Vector3.new(6, 4, 0.4), hinge * CFrame.new(-side * 3, 0, 0), C.Wood, Enum.Material.WoodPlanks)
		decorate(door)
	end
	local arch = b.part(gate, "Arch", Vector3.new(17, 1, 1.2), CFrame.new(0, 7.8, z), C.WoodDark, Enum.Material.Wood)
	decorate(arch)
	gate:SetAttribute("GateCenter", Vector3.new(0, 3, z))
end

-- Pedestal positions for a floor (local space, relative to the floor's base height).
function MansionBuilder.PedestalLayout(count: number): { Vector3 }
	local out = {}
	local xs = { -15, -5.5, 5.5, 15 }
	local zs = { M.centerZ - 7, M.centerZ + 7 }
	local i = 0
	for _, z in zs do
		for _, x in xs do
			i += 1
			if i > count then
				return out
			end
			table.insert(out, Vector3.new(x, 0, z))
		end
	end
	-- Extra pedestals (game pass) line the side walls.
	local extra = { Vector3.new(-19.5, 0, M.centerZ + 15), Vector3.new(19.5, 0, M.centerZ + 15), Vector3.new(-19.5, 0, M.centerZ - 2), Vector3.new(19.5, 0, M.centerZ - 2) }
	for _, p in extra do
		i += 1
		if i > count then
			break
		end
		table.insert(out, p)
	end
	return out
end

local function buildPedestal(b: Builder, parent: Instance, index: number, floor: number, at: Vector3): Model
	local ped = model(`Pedestal_{index}`, parent)
	ped:SetAttribute("Index", index)
	ped:SetAttribute("Floor", floor)
	local base = b.part(ped, "Base", Vector3.new(1.4, 6, 6), upright(at.X, at.Y + 0.7, at.Z), C.StoneDark, Enum.Material.Slate, Enum.PartType.Cylinder)
	local ring = b.part(ped, "GlowRing", Vector3.new(0.3, 6.4, 6.4), upright(at.X, at.Y + 1.45, at.Z), C.Ecto, Enum.Material.Neon, Enum.PartType.Cylinder)
	decorate(ring)
	local top = b.part(ped, "Top", Vector3.new(0.4, 5, 5), upright(at.X, at.Y + 1.7, at.Z), C.Stone, Enum.Material.Marble, Enum.PartType.Cylinder)
	local anchor = Instance.new("Attachment")
	anchor.Name = "BrainrotAnchor"
	-- Cylinder's local X axis is world up after the 90° roll, so "up" is +X in the part's space.
	anchor.CFrame = CFrame.new(0.2, 0, 0) * CFrame.Angles(0, 0, math.rad(-90))
	anchor.Parent = top
	ped.PrimaryPart = base
	return ped
end

local function buildWindow(b: Builder, parent: Instance, at: CFrame, size: Vector2)
	local frame = b.part(parent, "WindowFrame", Vector3.new(size.X + 1, size.Y + 1, 0.4), at, C.WallTrim, Enum.Material.Wood)
	decorate(frame)
	local glass = b.part(parent, "Window", Vector3.new(size.X, size.Y, 0.5), at, C.Window, Enum.Material.Neon)
	decorate(glass)
	glass.Transparency = 0.15
	-- Cross bars
	local bar1 = b.part(parent, "Bar", Vector3.new(0.3, size.Y, 0.6), at, C.WallTrim, Enum.Material.Wood)
	decorate(bar1)
	local bar2 = b.part(parent, "Bar", Vector3.new(size.X, 0.3, 0.6), at, C.WallTrim, Enum.Material.Wood)
	decorate(bar2)
end

-- Builds storey `floor` (1-based). Phase 2 builds Floor 1; later floors reuse the same shell.
function MansionBuilder.BuildFloor(plot: Model, floor: number, pedestalCount: number): Model
	local root = plot:GetAttribute("PlotCFrame") :: CFrame
	local b = newBuilder(root)
	local mansion = plot:FindFirstChild("Mansion") or model("Mansion", plot)
	local storey = model(`Floor{floor}`, mansion)
	local y0 = M.foundation + (floor - 1) * FLOOR_H -- top of this storey's floor
	local w, d, t = M.width, M.depth, M.wall

	if floor == 1 then
		b.part(storey, "Foundation", Vector3.new(w + 2, M.foundation, d + 2), CFrame.new(0, M.foundation / 2, M.centerZ), C.StoneDark, Enum.Material.Cobblestone)
	end
	-- Floor planks (two alternating tones read as "creaky boards").
	local planks = 8
	for i = 1, planks do
		local px = -w / 2 + t + (i - 0.5) * ((w - 2 * t) / planks)
		local tone = if i % 2 == 0 then C.Wood else C.WoodDark
		b.part(storey, "Plank", Vector3.new((w - 2 * t) / planks - 0.1, 0.3, d - 2 * t), CFrame.new(px, y0 + 0.15, M.centerZ), tone, Enum.Material.WoodPlanks)
	end

	-- Walls: back, sides, and a front wall with a doorway.
	local wallY = y0 + FLOOR_H / 2
	b.part(storey, "BackWall", Vector3.new(w, FLOOR_H, t), CFrame.new(0, wallY, M.centerZ + d / 2 - t / 2), C.Wall, Enum.Material.WoodPlanks)
	for _, side in { -1, 1 } do
		b.part(storey, "SideWall", Vector3.new(t, FLOOR_H, d), CFrame.new(side * (w / 2 - t / 2), wallY, M.centerZ), C.Wall, Enum.Material.WoodPlanks)
		for _, z in { M.centerZ - 8, M.centerZ + 8 } do
			buildWindow(b, storey, CFrame.new(side * (w / 2 + 0.1), wallY + 1, z) * CFrame.Angles(0, math.rad(90), 0), Vector2.new(5, 6))
		end
	end
	local doorW = if floor == 1 then M.doorWidth else 0
	local segW = (w - doorW) / 2
	for _, side in { -1, 1 } do
		b.part(storey, "FrontWall", Vector3.new(segW, FLOOR_H, t), CFrame.new(side * (doorW / 2 + segW / 2), wallY, FRONT_Z + t / 2), C.Wall, Enum.Material.WoodPlanks)
		buildWindow(b, storey, CFrame.new(side * 14, wallY + 1, FRONT_Z - 0.1), Vector2.new(6, 6))
	end
	if floor == 1 then
		local lintelH = FLOOR_H - M.doorHeight
		b.part(storey, "Lintel", Vector3.new(doorW, lintelH, t), CFrame.new(0, y0 + M.doorHeight + lintelH / 2, FRONT_Z + t / 2), C.Wall, Enum.Material.WoodPlanks)
		local trim = b.part(storey, "DoorTrim", Vector3.new(doorW + 1.2, 0.8, t + 0.4), CFrame.new(0, y0 + M.doorHeight + 0.4, FRONT_Z + t / 2), C.Pumpkin, Enum.Material.Neon)
		decorate(trim)
	end
	-- Corner trims make the silhouette pop.
	for _, sx in { -1, 1 } do
		for _, sz in { -1, 1 } do
			b.part(storey, "CornerTrim", Vector3.new(1.6, FLOOR_H, 1.6), CFrame.new(sx * w / 2, wallY, M.centerZ + sz * d / 2), C.WallTrim, Enum.Material.Wood)
		end
	end
	-- Ceiling (doubles as the next floor's base).
	b.part(storey, "Ceiling", Vector3.new(w, 1, d), CFrame.new(0, y0 + FLOOR_H + 0.5, M.centerZ), C.WallTrim, Enum.Material.Wood)

	-- Hanging ghost-lamp in the middle of the room.
	local lamp = b.part(storey, "CeilingLamp", Vector3.new(2, 2, 2), CFrame.new(0, y0 + FLOOR_H - 2.5, M.centerZ), C.Ecto, Enum.Material.Neon, Enum.PartType.Ball)
	decorate(lamp)
	light(lamp, C.Ecto, 26, 1.1)

	-- Pedestals
	local pedestals = plot:FindFirstChild("Pedestals") or folder("Pedestals", plot)
	local startIndex = #pedestals:GetChildren()
	for i, at in MansionBuilder.PedestalLayout(pedestalCount) do
		buildPedestal(b, pedestals, startIndex + i, floor, Vector3.new(at.X, y0 + 0.3, at.Z))
	end
	return storey
end

local function buildPorch(b: Builder, plot: Model)
	local porch = model("Porch", plot)
	local depth, width, height = 8, 24, M.foundation
	local z0 = FRONT_Z - depth / 2
	-- Deck boards with slightly different tones and tilts: the creaky porch.
	for i = 1, 6 do
		local z = FRONT_Z - (i - 0.5) * (depth / 6)
		local tone = if i % 2 == 0 then C.Wood else C.WoodDark
		local board = b.part(porch, "Board", Vector3.new(width, height, depth / 6 - 0.08), CFrame.new(0, height / 2, z) * CFrame.Angles(math.rad((i % 3 - 1) * 0.6), 0, 0), tone, Enum.Material.WoodPlanks)
		board:SetAttribute("Creaky", true) -- client plays a creak when stepped on
	end
	-- Steps down to the path.
	for i = 1, 2 do
		b.part(porch, "Step", Vector3.new(10, height - i * 0.5, 1.5), CFrame.new(0, (height - i * 0.5) / 2, FRONT_Z - depth - (i - 0.5) * 1.5), C.WoodDark, Enum.Material.WoodPlanks)
	end
	-- Posts, awning and lanterns.
	for _, x in { -width / 2 + 1, width / 2 - 1 } do
		b.part(porch, "Post", Vector3.new(1, 9, 1), CFrame.new(x, height + 4.5, FRONT_Z - depth + 0.8), C.WoodDark, Enum.Material.Wood)
		local lantern = b.part(porch, "Lantern", Vector3.new(1.2, 1.6, 1.2), CFrame.new(x, height + 6.5, FRONT_Z - depth + 0.2), C.Window, Enum.Material.Neon)
		decorate(lantern)
		lantern:SetAttribute("Interactive", "Lantern") -- client sways it
		light(lantern, C.Window, 16, 1.4)
	end
	local awning = Instance.new("WedgePart")
	awning.Name = "Awning"
	awning.Anchored = true
	awning.Size = Vector3.new(width + 2, 2, depth + 1)
	-- WedgePart: tall side at +Z (against the wall), slope facing the plaza (-Z).
	awning.CFrame = b.root * CFrame.new(0, height + 10, z0 - 0.5)
	awning.Color = C.Roof
	awning.Material = Enum.Material.Slate
	awning.Parent = porch
	-- Pumpkins on the porch.
	for i, x in { -9, 9.5, -6.5 } do
		local size = if i == 3 then 1.6 else 2.4
		local pumpkin = b.part(porch, "Pumpkin", Vector3.new(size, size * 0.8, size), CFrame.new(x, height + size * 0.4, z0 - 1 + i), C.Pumpkin, Enum.Material.SmoothPlastic, Enum.PartType.Ball)
		decorate(pumpkin)
		local stem = b.part(porch, "Stem", Vector3.new(0.3, 0.6, 0.3), CFrame.new(x, height + size * 0.8 + 0.2, z0 - 1 + i), C.Stem)
		decorate(stem)
		if i == 1 then
			light(pumpkin, C.Pumpkin, 10, 1)
		end
	end
end

local function buildRoof(b: Builder, plot: Model, floors: number): Model
	local mansion = plot:FindFirstChild("Mansion") :: Model
	local old = mansion:FindFirstChild("Roof")
	if old then
		old:Destroy()
	end
	local roof = model("Roof", mansion)
	local baseY = M.foundation + floors * FLOOR_H + 1
	local w, d = M.width + 4, M.depth + 4
	local h = 10
	for _, side in { -1, 1 } do
		local wedge = Instance.new("WedgePart")
		wedge.Name = "RoofSlope"
		wedge.Anchored = true
		wedge.Size = Vector3.new(w, h, d / 2)
		wedge.CFrame = b.root * CFrame.new(0, baseY + h / 2, M.centerZ + side * d / 4) * CFrame.Angles(0, if side == -1 then 0 else math.rad(180), 0)
		wedge.Color = C.Roof
		wedge.Material = Enum.Material.Slate
		wedge.Parent = roof
	end
	-- Crooked chimney with a green ectoplasm glow.
	b.part(roof, "Chimney", Vector3.new(3, 7, 3), CFrame.new(13, baseY + 6, M.centerZ + 6) * CFrame.Angles(0, 0, math.rad(-6)), C.StoneDark, Enum.Material.Brick)
	local smoke = b.part(roof, "ChimneyGlow", Vector3.new(2.4, 0.4, 2.4), CFrame.new(13.4, baseY + 9.6, M.centerZ + 6), C.Ecto, Enum.Material.Neon)
	decorate(smoke)
	smoke:SetAttribute("Interactive", "ChimneySmoke") -- client adds drifting smoke particles
	roof:SetAttribute("TopY", baseY + h)
	return roof
end

local function buildSign(b: Builder, plot: Model, topY: number)
	local sign = model("OwnerSign", plot)
	local y = topY + 5
	local z = FRONT_Z - 1
	for _, x in { -11, 11 } do
		b.part(sign, "Pole", Vector3.new(0.8, 9, 0.8), CFrame.new(x, y - 3.5, z + 0.8), C.WoodDark, Enum.Material.Wood)
	end
	local board = b.part(sign, "Board", Vector3.new(30, 7, 0.8), CFrame.new(0, y, z), C.SignBoard, Enum.Material.Wood)
	local edge = b.part(sign, "Edge", Vector3.new(31, 7.8, 0.6), CFrame.new(0, y, z + 0.2), C.Ecto, Enum.Material.Neon)
	decorate(edge)
	for _, face in { Enum.NormalId.Front, Enum.NormalId.Back } do
		local gui = Instance.new("SurfaceGui")
		gui.Name = if face == Enum.NormalId.Front then "SignFront" else "SignBack"
		gui.Face = face
		gui.SizingMode = Enum.SurfaceGuiSizingMode.PixelsPerStud
		gui.PixelsPerStud = 30
		gui.LightInfluence = 0
		gui.Parent = board
		local title = Instance.new("TextLabel")
		title.Name = "Title"
		title.BackgroundTransparency = 1
		title.Size = UDim2.new(1, -30, 0.58, 0)
		title.Position = UDim2.new(0, 15, 0, 6)
		title.Font = Theme.Fonts.Display
		title.TextScaled = true
		title.TextColor3 = Theme.Colors.White
		title.Text = "Empty Plot"
		local s1 = Instance.new("UIStroke")
		s1.Thickness = 3
		s1.Color = Theme.Colors.Ink
		s1.Parent = title
		title.Parent = gui
		local income = Instance.new("TextLabel")
		income.Name = "Income"
		income.BackgroundTransparency = 1
		income.Size = UDim2.new(1, -30, 0.36, 0)
		income.Position = UDim2.new(0, 15, 0.6, 0)
		income.Font = Theme.Fonts.Body
		income.TextScaled = true
		income.TextColor3 = Theme.Colors.Ecto
		income.Text = "waiting for a ghost host..."
		local s2 = Instance.new("UIStroke")
		s2.Thickness = 2
		s2.Color = Theme.Colors.Ink
		s2.Parent = income
		income.Parent = gui
	end
	return board
end

-- ------------------------------------------------------------------ public

-- Builds a complete plot (Floor 1) at `cframe` and returns its Model.
function MansionBuilder.BuildPlot(index: number, cframe: CFrame, parent: Instance): Model
	local plot = Instance.new("Model")
	plot.Name = `Plot_{index}`
	plot:SetAttribute("PlotIndex", index)
	plot:SetAttribute("OwnerUserId", 0)
	plot:SetAttribute("OwnerName", "")
	plot:SetAttribute("PlotCFrame", cframe)
	plot:SetAttribute("FloorsBuilt", 0)
	local b = newBuilder(cframe)

	buildLot(b, plot)
	buildGate(b, plot)
	buildPorch(b, plot)
	MansionBuilder.BuildFloor(plot, 1, 8)
	plot:SetAttribute("FloorsBuilt", 1)
	local roof = buildRoof(b, plot, 1)
	buildSign(b, plot, roof:GetAttribute("TopY") :: number)

	-- Spawn on the porch, facing the plaza.
	local spawn = b.part(plot, "SpawnPoint", Vector3.new(4, 1, 4), CFrame.new(0, M.foundation + 0.5, FRONT_Z - 4) * CFrame.Angles(0, 0, 0), C.Ecto)
	spawn.Transparency = 1
	decorate(spawn)

	-- Claim zone: the front doorway area. Touch-enabled for the stealing phase.
	local claim = b.part(plot, "ClaimZone", PLOT.claimZoneSize, CFrame.new(0, M.foundation + PLOT.claimZoneSize.Y / 2, FRONT_Z + PLOT.claimZoneSize.Z / 2 - 2), C.Ecto, Enum.Material.ForceField)
	claim.Transparency = 1
	claim.CanCollide = false
	claim.CanQuery = false
	claim.CastShadow = false

	plot.PrimaryPart = plot:FindFirstChild("Lot"):FindFirstChild("Ground") :: BasePart
	plot.Parent = parent
	return plot
end

-- Updates the owner sign on both faces.
function MansionBuilder.SetSign(plot: Model, title: string, incomeText: string)
	local sign = plot:FindFirstChild("OwnerSign")
	local board = sign and sign:FindFirstChild("Board")
	if not board then
		return
	end
	for _, guiName in { "SignFront", "SignBack" } do
		local gui = board:FindFirstChild(guiName)
		if gui then
			(gui:FindFirstChild("Title") :: TextLabel).Text = title;
			(gui:FindFirstChild("Income") :: TextLabel).Text = incomeText
		end
	end
end

return MansionBuilder
