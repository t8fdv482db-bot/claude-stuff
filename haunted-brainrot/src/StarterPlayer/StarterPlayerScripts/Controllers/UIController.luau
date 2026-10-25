--!strict
--[[
	UIController
	Mobile-first HUD: currency pills that tick up smoothly and bounce on gains, plus toast
	notifications from the server (Net "Notify"). Later phases add more panels through
	UIController.Toast and UIController.Screen.

	Respects the player's Reduced Motion setting (no bounces/slides, instant fades).
]]

local Players = game:GetService("Players")
local ReplicatedStorage = game:GetService("ReplicatedStorage")
local RunService = game:GetService("RunService")
local TweenService = game:GetService("TweenService")
local Workspace = game:GetService("Workspace")

local Shared = ReplicatedStorage:WaitForChild("Shared")
local Format = require(Shared.Util.Format)
local Net = require(Shared.Net)
local Theme = require(Shared.Theme)

local player = Players.LocalPlayer

local UIController = {}

local screen: ScreenGui
local toastHolder: Frame
local counters: { [string]: { label: TextLabel, scale: UIScale, shown: number } } = {}

local CURRENCIES = { "Ectoplasm", "Candy", "SoulGems" }
local TOAST_COLORS = {
	Info = Theme.Colors.Info,
	Success = Theme.Colors.Success,
	Error = Theme.Colors.Error,
	Event = Theme.Colors.Orange,
}

local function reducedMotion(): boolean
	return player:GetAttribute("Setting_reducedMotion") == true
end

local function corner(parent: Instance, radius: UDim?)
	local c = Instance.new("UICorner")
	c.CornerRadius = radius or Theme.CornerRadius
	c.Parent = parent
end

local function stroke(parent: Instance, thickness: number, color: Color3?)
	local s = Instance.new("UIStroke")
	s.Thickness = thickness
	s.Color = color or Theme.Colors.Ink
	s.ApplyStrokeMode = Enum.ApplyStrokeMode.Border
	s.Parent = parent
end

local function textStroke(label: TextLabel)
	local s = Instance.new("UIStroke")
	s.Thickness = 2
	s.Color = Theme.Colors.Ink
	s.Parent = label
end

-- Scales the whole HUD for the screen: phones get chunkier relative sizes.
local function fitScale(uiScale: UIScale)
	local function update()
		local camera = Workspace.CurrentCamera
		if not camera then
			return
		end
		local size = camera.ViewportSize
		local short = math.min(size.X, size.Y)
		uiScale.Scale = math.clamp(short / 720, 0.7, 1.4)
	end
	update()
	local camera = Workspace.CurrentCamera
	if camera then
		camera:GetPropertyChangedSignal("ViewportSize"):Connect(update)
	end
end

local function makeCounter(parent: Instance, currency: string, order: number, color: Color3)
	local pill = Instance.new("Frame")
	pill.Name = currency
	pill.LayoutOrder = order
	pill.Size = UDim2.fromOffset(170, 48)
	pill.BackgroundColor3 = Theme.Colors.PurpleDark
	pill.BackgroundTransparency = 0.1
	corner(pill, UDim.new(1, 0))
	stroke(pill, 3, color)

	local scale = Instance.new("UIScale")
	scale.Parent = pill

	local icon = Instance.new("TextLabel")
	icon.BackgroundTransparency = 1
	icon.Size = UDim2.new(0, 44, 1, 0)
	icon.Position = UDim2.fromOffset(6, 0)
	icon.Text = Theme.CurrencyIcons[currency]
	icon.TextScaled = true
	icon.Font = Theme.Fonts.Body
	icon.Parent = pill

	local label = Instance.new("TextLabel")
	label.BackgroundTransparency = 1
	label.Position = UDim2.fromOffset(50, 4)
	label.Size = UDim2.new(1, -60, 1, -8)
	label.Font = Theme.Fonts.Body
	label.TextScaled = true
	label.TextXAlignment = Enum.TextXAlignment.Left
	label.TextColor3 = color
	label.Text = "0"
	textStroke(label)
	label.Parent = pill

	pill.Parent = parent
	local start = (player:GetAttribute(currency) :: number?) or 0
	label.Text = Format.Abbreviate(start)
	counters[currency] = { label = label, scale = scale, shown = start }
end

local function bounce(scale: UIScale)
	if reducedMotion() then
		return
	end
	scale.Scale = 1.18
	TweenService:Create(scale, TweenInfo.new(0.35, Enum.EasingStyle.Back, Enum.EasingDirection.Out), { Scale = 1 }):Play()
end

local function buildHud()
	screen = Instance.new("ScreenGui")
	screen.Name = "HUD"
	screen.ResetOnSpawn = false
	screen.IgnoreGuiInset = false
	screen.ZIndexBehavior = Enum.ZIndexBehavior.Sibling
	local uiScale = Instance.new("UIScale")
	uiScale.Parent = screen
	fitScale(uiScale)

	local bar = Instance.new("Frame")
	bar.Name = "Currencies"
	bar.BackgroundTransparency = 1
	bar.AnchorPoint = Vector2.new(0.5, 0)
	bar.Position = UDim2.new(0.5, 0, 0, 8)
	bar.Size = UDim2.fromOffset(560, 52)
	local layout = Instance.new("UIListLayout")
	layout.FillDirection = Enum.FillDirection.Horizontal
	layout.HorizontalAlignment = Enum.HorizontalAlignment.Center
	layout.Padding = UDim.new(0, 10)
	layout.SortOrder = Enum.SortOrder.LayoutOrder
	layout.Parent = bar
	bar.Parent = screen

	makeCounter(bar, "Ectoplasm", 1, Theme.Colors.Ecto)
	makeCounter(bar, "Candy", 2, Theme.Colors.Candy)
	makeCounter(bar, "SoulGems", 3, Theme.Colors.Gem)

	toastHolder = Instance.new("Frame")
	toastHolder.Name = "Toasts"
	toastHolder.BackgroundTransparency = 1
	toastHolder.AnchorPoint = Vector2.new(0.5, 0)
	toastHolder.Position = UDim2.new(0.5, 0, 0, 70)
	toastHolder.Size = UDim2.fromOffset(460, 300)
	local tl = Instance.new("UIListLayout")
	tl.HorizontalAlignment = Enum.HorizontalAlignment.Center
	tl.Padding = UDim.new(0, 6)
	tl.SortOrder = Enum.SortOrder.LayoutOrder
	tl.Parent = toastHolder
	toastHolder.Parent = screen

	screen.Parent = player:WaitForChild("PlayerGui")
end

local toastCount = 0

-- Shows a short message that pops in, waits, and fades away.
function UIController.Toast(text: string, style: string?, seconds: number?)
	if not toastHolder then
		return
	end
	toastCount += 1
	local frame = Instance.new("Frame")
	frame.LayoutOrder = toastCount
	frame.Size = UDim2.fromOffset(440, 48)
	frame.BackgroundColor3 = TOAST_COLORS[style or "Info"] or Theme.Colors.Info
	corner(frame, UDim.new(0.4, 0))
	stroke(frame, 3)
	local scale = Instance.new("UIScale")
	scale.Scale = if reducedMotion() then 1 else 0.3
	scale.Parent = frame

	local label = Instance.new("TextLabel")
	label.BackgroundTransparency = 1
	label.Size = UDim2.new(1, -20, 1, -8)
	label.Position = UDim2.fromOffset(10, 4)
	label.Font = Theme.Fonts.Body
	label.TextScaled = true
	label.TextColor3 = Theme.Colors.White
	label.Text = text
	textStroke(label)
	label.Parent = frame
	frame.Parent = toastHolder

	if not reducedMotion() then
		TweenService:Create(scale, TweenInfo.new(0.35, Enum.EasingStyle.Back, Enum.EasingDirection.Out), { Scale = 1 }):Play()
	end
	task.delay(seconds or 2.5, function()
		local fade = TweenInfo.new(if reducedMotion() then 0.1 else 0.4)
		TweenService:Create(frame, fade, { BackgroundTransparency = 1 }):Play()
		TweenService:Create(label, fade, { TextTransparency = 1 }):Play()
		task.wait(0.45)
		frame:Destroy()
	end)
	-- Keep at most 4 toasts on screen.
	local toasts = {}
	for _, c in toastHolder:GetChildren() do
		if c:IsA("Frame") then
			table.insert(toasts, c)
		end
	end
	table.sort(toasts, function(a, b)
		return a.LayoutOrder < b.LayoutOrder
	end)
	for i = 1, #toasts - 4 do
		toasts[i]:Destroy()
	end
end

function UIController.Init()
	buildHud()
end

function UIController.Start()
	for _, currency in CURRENCIES do
		player:GetAttributeChangedSignal(currency):Connect(function()
			local c = counters[currency]
			local new = (player:GetAttribute(currency) :: number?) or 0
			if c and new > c.shown then
				bounce(c.scale)
			end
		end)
	end

	-- Smoothly tick displayed values toward the real balance.
	RunService.RenderStepped:Connect(function(dt)
		for currency, c in counters do
			local target = (player:GetAttribute(currency) :: number?) or 0
			if c.shown ~= target then
				local diff = target - c.shown
				local step = diff * math.min(1, dt * 8)
				if math.abs(diff) < 1 or reducedMotion() then
					c.shown = target
				else
					c.shown += step
				end
				c.label.Text = Format.Abbreviate(math.floor(c.shown + 0.5))
			end
		end
	end)

	Net.Client.On("Notify", function(text: string, style: string?)
		if type(text) == "string" then
			UIController.Toast(text, style)
		end
	end)
end

return UIController
