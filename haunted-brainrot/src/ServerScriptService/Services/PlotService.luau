--!strict
--[[
	PlotService
	Owns the 8 Haunted Plots arranged in a ring around the plaza.

	* Builds the world ground and every plot (Floor 1 mansion) at server start.
	* Assigns each player the lowest free plot once their data has loaded, puts their name on the
	  owner sign, and spawns them on their porch (every respawn too).
	* Frees and resets the plot when the player leaves.
	* Keeps the sign's income line in sync with the player's "IncomePerSecond" attribute (set by
	  the income system).

	API:
	  PlotService.GetPlot(player) -> Model?
	  PlotService.GetOwner(plot) -> Player?
	  PlotService.GetPlotByIndex(i) -> Model
	  PlotService.GetPedestals(plot) -> { Model }    sorted by index
	  PlotService.GetSpawnCFrame(plot) -> CFrame
	  PlotService.PlotAssigned:Connect(fn(player, plot))
	  PlotService.PlotReleased:Connect(fn(player, plot))
]]

local Players = game:GetService("Players")
local ReplicatedStorage = game:GetService("ReplicatedStorage")
local Workspace = game:GetService("Workspace")

local Shared = ReplicatedStorage.Shared
local Format = require(Shared.Util.Format)
local GameConfig = require(Shared.Config.GameConfig)
local Net = require(Shared.Net)
local Signal = require(Shared.Util.Signal)

local Lib = script.Parent.Parent.Lib
local MansionBuilder = require(Lib.MansionBuilder)
local PlotLayout = require(Lib.PlotLayout)
local WorldBuilder = require(Lib.WorldBuilder)

local DataService = require(script.Parent.DataService)

local PlotService = {
	PlotAssigned = Signal.new() :: Signal.Signal<Player, Model>,
	PlotReleased = Signal.new() :: Signal.Signal<Player, Model>,
}

local plots: { Model } = {}
local owners: { [number]: Player } = {} -- plot index -> owner
local plotOf: { [Player]: number } = {}
local connections: { [Player]: { any } } = {}

local KICK_FULL = "👻 This haunted server is full! Please join another one."
local EMPTY_TITLE = "Empty Plot"
local EMPTY_SUBTITLE = "waiting for a ghost host..."

function PlotService.GetPlotByIndex(index: number): Model
	return plots[index]
end

function PlotService.GetPlot(player: Player): Model?
	local index = plotOf[player]
	return if index then plots[index] else nil
end

function PlotService.GetOwner(plot: Model): Player?
	local index = plot:GetAttribute("PlotIndex") :: number?
	return if index then owners[index] else nil
end

function PlotService.GetPedestals(plot: Model): { Model }
	local folder = plot:FindFirstChild("Pedestals")
	local list = {}
	if folder then
		for _, p in folder:GetChildren() do
			if p:IsA("Model") then
				table.insert(list, p)
			end
		end
	end
	table.sort(list, function(a, b)
		return (a:GetAttribute("Index") :: number) < (b:GetAttribute("Index") :: number)
	end)
	return list
end

function PlotService.GetSpawnCFrame(plot: Model): CFrame
	local spawn = plot:FindFirstChild("SpawnPoint") :: BasePart
	-- Stand on top of the spawn pad, facing the plaza (the pad's LookVector).
	return spawn.CFrame * CFrame.new(0, 3.5, 0)
end

local function signTitle(player: Player): string
	-- DisplayNames are already moderated by Roblox; custom base names (later) go through TextService.
	return `👻 {player.DisplayName}'s Mansion`
end

local function incomeText(player: Player): string
	local perSecond = (player:GetAttribute("IncomePerSecond") :: number?) or 0
	return `💚 {Format.PerSecond(perSecond)}`
end

local function teleportHome(player: Player, character: Model)
	local plot = PlotService.GetPlot(player)
	if not plot then
		return
	end
	local root = character:FindFirstChild("HumanoidRootPart") or character:WaitForChild("HumanoidRootPart", 5)
	if root then
		character:PivotTo(PlotService.GetSpawnCFrame(plot))
	end
end

local function assign(player: Player)
	if plotOf[player] or player.Parent == nil then
		return
	end
	local index: number? = nil
	for i = 1, #plots do
		if owners[i] == nil then
			index = i
			break
		end
	end
	if not index then
		player:Kick(KICK_FULL)
		return
	end
	local plot = plots[index]
	owners[index] = player
	plotOf[player] = index
	plot:SetAttribute("OwnerUserId", player.UserId)
	plot:SetAttribute("OwnerName", player.DisplayName)
	player:SetAttribute("PlotIndex", index)
	MansionBuilder.SetSign(plot, signTitle(player), incomeText(player))

	local conns = {}
	table.insert(
		conns,
		player:GetAttributeChangedSignal("IncomePerSecond"):Connect(function()
			MansionBuilder.SetSign(plot, signTitle(player), incomeText(player))
		end)
	)
	table.insert(
		conns,
		player.CharacterAdded:Connect(function(character)
			-- Defer so the default spawn finishes first, then move the character home.
			task.defer(teleportHome, player, character)
		end)
	)
	connections[player] = conns
	if player.Character then
		task.defer(teleportHome, player, player.Character)
	end

	Net.Server.Fire("Notify", player, "Welcome to your Haunted Mansion! 👻", "Success")
	PlotService.PlotAssigned:Fire(player, plot)
end

local function release(player: Player)
	local index = plotOf[player]
	if not index then
		return
	end
	local plot = plots[index]
	for _, c in connections[player] or {} do
		c:Disconnect()
	end
	connections[player] = nil
	plotOf[player] = nil
	owners[index] = nil
	plot:SetAttribute("OwnerUserId", 0)
	plot:SetAttribute("OwnerName", "")
	MansionBuilder.SetSign(plot, EMPTY_TITLE, EMPTY_SUBTITLE)
	PlotService.PlotReleased:Fire(player, plot)
end

function PlotService.Init()
	local map = Workspace:FindFirstChild("Map") or WorldBuilder.Build(Workspace)
	local plotFolder = Instance.new("Folder")
	plotFolder.Name = "Plots"
	for i, cf in PlotLayout.All() do
		local plot = MansionBuilder.BuildPlot(i, cf, plotFolder)
		MansionBuilder.SetSign(plot, EMPTY_TITLE, EMPTY_SUBTITLE)
		plots[i] = plot
	end
	plotFolder.Parent = map
end

function PlotService.Start()
	DataService.Loaded:Connect(assign)
	Players.PlayerRemoving:Connect(release)
	for _, player in Players:GetPlayers() do
		if DataService.IsLoaded(player) then
			assign(player)
		end
	end
	if Players.MaxPlayers > GameConfig.Plots.count then
		warn(`[PlotService] Players.MaxPlayers ({Players.MaxPlayers}) exceeds plot count ({GameConfig.Plots.count}); set Max Players to {GameConfig.Plots.count} in Game Settings.`)
	end
end

return PlotService
