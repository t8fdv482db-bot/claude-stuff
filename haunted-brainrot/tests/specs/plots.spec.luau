--!nocheck
local Context = require("../harness/Context")
local Shim = require("../harness/Shim")
local task = require("@lune/task")
local roblox = require("@lune/roblox")
local Vector3, CFrame, Instance = roblox.Vector3, roblox.CFrame, roblox.Instance

local function settle()
	for _ = 1, 6 do
		task.wait()
	end
end

local function boot(opts)
	local ctx = Context.new(opts)
	ctx.get("ReplicatedStorage/Shared/Net").Server.Init()
	local services = {}
	for _, name in { "DataService", "EconomyService", "PlotService" } do
		services[name] = ctx.get(`ServerScriptService/Services/{name}`)
		services[name].Init()
	end
	for _, name in { "DataService", "EconomyService", "PlotService" } do
		services[name].Start()
	end
	ctx.services = services
	return ctx
end

local function allParts(root)
	local out = {}
	for _, d in root:GetDescendants() do
		if d:IsA("BasePart") then
			table.insert(out, d)
		end
	end
	return out
end

return function(T)
	local describe, it, expect = T.describe, T.it, T.expect

	describe("PlotLayout", function()
		local ctx = Context.new()
		local PlotLayout = ctx.get("ServerScriptService/Lib/PlotLayout")
		local GameConfig = ctx.get("ReplicatedStorage/Shared/Config/GameConfig")

		it("places 8 plots on the ring, facing the plaza", function()
			local all = PlotLayout.All()
			expect(#all).toBe(8)
			for _, cf in all do
				local flat = Vector3.new(cf.Position.X, 0, cf.Position.Z)
				expect(flat.Magnitude).toBeNear(GameConfig.Plots.ringRadius, 1e-3)
				-- LookVector points at the centre
				local toCenter = (-flat).Unit
				expect(cf.LookVector:Dot(toCenter)).toBeNear(1, 1e-4)
			end
		end)
		it("keeps plot footprints apart", function()
			local all = PlotLayout.All()
			for i = 1, #all do
				local nextCf = all[i % #all + 1]
				local gap = (all[i].Position - nextCf.Position).Magnitude
				expect(gap).toBeGreaterThan(GameConfig.Plots.plotSize.X + 10)
			end
		end)
		it("finds which plot contains a point", function()
			local cf = PlotLayout.PlotCFrame(3)
			expect(PlotLayout.PlotAt(cf.Position + Vector3.new(0, 20, 0))).toBe(3)
			expect(PlotLayout.PlotAt(Vector3.new(0, 0, 0))).toBe(nil)
			expect(PlotLayout.Contains(3, (cf * CFrame.new(31, 0, 35)).Position)).toBe(true)
			expect(PlotLayout.Contains(3, (cf * CFrame.new(40, 0, 0)).Position)).toBe(false)
		end)
	end)

	describe("MansionBuilder", function()
		local ctx = Context.new()
		local MansionBuilder = ctx.get("ServerScriptService/Lib/MansionBuilder")
		local PlotLayout = ctx.get("ServerScriptService/Lib/PlotLayout")
		local GameConfig = ctx.get("ReplicatedStorage/Shared/Config/GameConfig")
		local folder = Instance.new("Folder")
		local cf = PlotLayout.PlotCFrame(2)
		local plot = MansionBuilder.BuildPlot(2, cf, folder)

		it("builds Floor 1 with 8 pedestals, each with a brainrot anchor", function()
			local pedestals = plot.Pedestals:GetChildren()
			expect(#pedestals).toBe(8)
			local seen = {}
			for _, p in pedestals do
				local idx = p:GetAttribute("Index")
				expect(seen[idx]).toBe(nil)
				seen[idx] = true
				expect(p:GetAttribute("Floor")).toBe(1)
				expect(p.Top:FindFirstChild("BrainrotAnchor") ~= nil).toBe(true)
			end
			expect(plot.Mansion:FindFirstChild("Floor1") ~= nil).toBe(true)
			expect(plot.Mansion:FindFirstChild("Roof") ~= nil).toBe(true)
			expect(plot:GetAttribute("FloorsBuilt")).toBe(1)
		end)

		it("anchors every part and keeps the mansion inside the plot", function()
			local size = GameConfig.Plots.plotSize
			for _, p in allParts(plot) do
				expect(p.Anchored).toBe(true)
				local lp = cf:PointToObjectSpace(p.CFrame.Position)
				if math.abs(lp.X) > size.X / 2 + 0.5 or math.abs(lp.Z) > size.Z / 2 + 0.5 then
					error(`{p:GetFullName()} sits outside the plot at {lp}`)
				end
			end
		end)

		it("puts pedestals inside the walls and the spawn on the porch facing the plaza", function()
			local M = MansionBuilder.Mansion
			for _, ped in plot.Pedestals:GetChildren() do
				local lp = cf:PointToObjectSpace(ped.Top.CFrame.Position)
				expect(math.abs(lp.X) < M.width / 2 - 3).toBe(true)
				expect(lp.Z > M.centerZ - M.depth / 2 + 3 and lp.Z < M.centerZ + M.depth / 2 - 3).toBe(true)
			end
			local spawn = plot.SpawnPoint
			expect(spawn.Transparency).toBe(1)
			expect(spawn.CanCollide).toBe(false)
			local lp = cf:PointToObjectSpace(spawn.CFrame.Position)
			expect(lp.Z < M.centerZ - M.depth / 2).toBe(true) -- in front of the front wall
			expect(spawn.CFrame.LookVector:Dot(cf.LookVector)).toBeNear(1, 1e-4)
		end)

		it("leaves a walkable doorway between the gate and the pedestals", function()
			-- No colliding part may sit in the 6-stud-wide corridor from the gate to the first pedestal row.
			local M = MansionBuilder.Mansion
			for _, p in allParts(plot) do
				if p.CanCollide and p.Name ~= "Ground" and p.Name ~= "Path" and p.Name ~= "Board" and p.Name ~= "Step"
					and p.Name ~= "Plank" and p.Name ~= "Foundation" and p.Name ~= "Graveyard" then
					local lp = cf:PointToObjectSpace(p.CFrame.Position)
					local half = p.Size / 2
					local inCorridorX = math.abs(lp.X) < 3 + math.min(half.X, half.Z)
					local inCorridorZ = lp.Z > -GameConfig.Plots.plotSize.Z / 2 + 2 and lp.Z < M.centerZ - 9
					local lowEnough = lp.Y - half.Y < 6
					if inCorridorX and inCorridorZ and lowEnough then
						error(`{p.Name} blocks the doorway at {lp}`)
					end
				end
			end
		end)

		it("has an owner sign with text on both faces and a claim zone", function()
			MansionBuilder.SetSign(plot, "👻 Casper's Mansion", "💚 12/s")
			for _, face in { "SignFront", "SignBack" } do
				local gui = plot.OwnerSign.Board[face]
				expect(gui.Title.Text).toBe("👻 Casper's Mansion")
				expect(gui.Income.Text).toBe("💚 12/s")
			end
			local claim = plot.ClaimZone
			expect(claim.CanCollide).toBe(false)
			expect(claim.CanTouch).toBe(true)
			expect(claim.Size).toBe(GameConfig.Plots.claimZoneSize)
		end)

		it("stays within a sensible part budget", function()
			local n = #allParts(plot)
			expect(n).toBeLessThan(260) -- x8 plots, keeps mobile performance healthy
		end)
	end)

	describe("PlotService", function()
		it("builds the world, all 8 plots and their empty signs", function()
			local ctx = boot()
			local ws = ctx.game:GetService("Workspace")
			local plots = ws.Map.Plots:GetChildren()
			expect(#plots).toBe(8)
			expect(ws.Map:FindFirstChild("PlazaSpawn") ~= nil).toBe(true)
			expect(#ws.Map.Paths:GetChildren()).toBe(8)
			expect(ws.Map.Plots.Plot_1.OwnerSign.Board.SignFront.Title.Text).toBe("Empty Plot")
		end)

		it("assigns the lowest free plot, names the sign and frees it on leave", function()
			local ctx = boot()
			local PS = ctx.services.PlotService
			local a = ctx.players:Join(1, "Alpha")
			local b = ctx.players:Join(2, "Beta")
			local c = ctx.players:Join(3, "Gamma")
			settle()
			expect(a:GetAttribute("PlotIndex")).toBe(1)
			expect(b:GetAttribute("PlotIndex")).toBe(2)
			expect(c:GetAttribute("PlotIndex")).toBe(3)
			local plotB = PS.GetPlot(b)
			expect(plotB:GetAttribute("OwnerUserId")).toBe(2)
			expect(PS.GetOwner(plotB)).toBe(b)
			expect(plotB.OwnerSign.Board.SignFront.Title.Text).toBe("👻 Beta's Mansion")
			expect(plotB.OwnerSign.Board.SignBack.Income.Text).toBe("💚 0/s")

			local released
			PS.PlotReleased:Connect(function(_, plot)
				released = plot
			end)
			ctx.players:Leave(b)
			settle()
			expect(released).toBe(plotB)
			expect(plotB:GetAttribute("OwnerUserId")).toBe(0)
			expect(plotB.OwnerSign.Board.SignFront.Title.Text).toBe("Empty Plot")

			local d = ctx.players:Join(4, "Delta")
			settle()
			expect(d:GetAttribute("PlotIndex")).toBe(2) -- reuses the freed plot
		end)

		it("kicks a 9th player politely when every plot is taken", function()
			local ctx = boot()
			for i = 1, 8 do
				ctx.players:Join(i, `P{i}`)
			end
			local extra = ctx.players:Join(9, "Late")
			settle()
			expect(extra:GetAttribute("PlotIndex")).toBe(nil)
			expect(Shim.kicked(extra)).toContain("full")
		end)

		it("updates the sign when income changes", function()
			local ctx = boot()
			local p = ctx.players:Join(5, "Earner")
			settle()
			p:SetAttribute("IncomePerSecond", 1234)
			p:GetAttributeChangedSignal("IncomePerSecond"):Fire()
			settle()
			expect(ctx.services.PlotService.GetPlot(p).OwnerSign.Board.SignFront.Income.Text).toBe("💚 1.23K/s")
		end)

		it("spawns the character on their own porch, and again after respawning", function()
			local ctx = boot()
			local PS = ctx.services.PlotService
			ctx.players:Join(6, "First")
			local p = ctx.players:Join(7, "Walker")
			settle()
			local char = p:LoadCharacter()
			settle()
			local plot = PS.GetPlot(p)
			local target = PS.GetSpawnCFrame(plot)
			expect((char.HumanoidRootPart.CFrame.Position - target.Position).Magnitude).toBeLessThan(0.01)
			-- Respawn
			local char2 = p:LoadCharacter()
			settle()
			expect((char2.HumanoidRootPart.CFrame.Position - target.Position).Magnitude).toBeLessThan(0.01)
		end)

		it("sends a welcome toast", function()
			local ctx = boot()
			local p = ctx.players:Join(8, "Hello")
			settle()
			local notify = ctx.game:GetService("ReplicatedStorage").Remotes.Notify
			local found = false
			for _, msg in Shim.sent(notify) do
				if msg.player == p and string.find(msg.args[1], "Haunted Mansion", 1, true) then
					found = true
				end
			end
			expect(found).toBe(true)
		end)
	end)
end
