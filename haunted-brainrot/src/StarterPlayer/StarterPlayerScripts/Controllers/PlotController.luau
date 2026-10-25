--!strict
--[[
	PlotController
	Helps the player find home: a bobbing "YOUR MANSION" marker above their own plot (only they
	see it) and a beam from their character to the gate for the first seconds after spawning.
]]

local Players = game:GetService("Players")
local ReplicatedStorage = game:GetService("ReplicatedStorage")
local RunService = game:GetService("RunService")
local Workspace = game:GetService("Workspace")

local Theme = require(ReplicatedStorage:WaitForChild("Shared").Theme)

local player = Players.LocalPlayer

local PlotController = {}

local marker: BillboardGui? = nil
local bobConnection: RBXScriptConnection? = nil

local function getPlot(): Model?
	local index = player:GetAttribute("PlotIndex")
	if type(index) ~= "number" then
		return nil
	end
	local map = Workspace:WaitForChild("Map", 10)
	local plots = map and map:WaitForChild("Plots", 10)
	return plots and plots:WaitForChild(`Plot_{index}`, 10) :: Model?
end

local function clearMarker()
	if marker then
		marker:Destroy()
		marker = nil
	end
	if bobConnection then
		bobConnection:Disconnect()
		bobConnection = nil
	end
end

local function showMarker()
	clearMarker()
	local plot = getPlot()
	if not plot then
		return
	end
	local sign = plot:WaitForChild("OwnerSign", 10)
	local board = sign and sign:WaitForChild("Board", 10) :: BasePart?
	if not board then
		return
	end
	local gui = Instance.new("BillboardGui")
	gui.Name = "YourMansionMarker"
	gui.Adornee = board
	gui.AlwaysOnTop = true
	gui.Size = UDim2.fromOffset(220, 70)
	gui.StudsOffsetWorldSpace = Vector3.new(0, 9, 0)
	gui.LightInfluence = 0
	gui.MaxDistance = 1000

	local label = Instance.new("TextLabel")
	label.BackgroundTransparency = 1
	label.Size = UDim2.fromScale(1, 1)
	label.Font = Theme.Fonts.Display
	label.TextScaled = true
	label.TextColor3 = Theme.Colors.Ecto
	label.Text = "⬇ YOUR MANSION ⬇"
	local stroke = Instance.new("UIStroke")
	stroke.Thickness = 3
	stroke.Color = Theme.Colors.Ink
	stroke.Parent = label
	label.Parent = gui
	gui.Parent = player:WaitForChild("PlayerGui")
	marker = gui

	local t = 0
	bobConnection = RunService.RenderStepped:Connect(function(dt)
		t += dt
		if player:GetAttribute("Setting_reducedMotion") == true then
			gui.StudsOffsetWorldSpace = Vector3.new(0, 9, 0)
		else
			gui.StudsOffsetWorldSpace = Vector3.new(0, 9 + math.sin(t * 3) * 0.8, 0)
		end
	end)
end

function PlotController.GetPlot(): Model?
	return getPlot()
end

function PlotController.Start()
	player:GetAttributeChangedSignal("PlotIndex"):Connect(function()
		if player:GetAttribute("PlotIndex") then
			showMarker()
		else
			clearMarker()
		end
	end)
	if player:GetAttribute("PlotIndex") then
		showMarker()
	end
end

return PlotController
