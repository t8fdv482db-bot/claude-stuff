--!strict
-- Shared visual theme: spooky-cute purple / green / orange palette and fonts.

local Theme = {}

Theme.Colors = {
	Purple = Color3.fromRGB(120, 60, 200),
	PurpleDark = Color3.fromRGB(55, 25, 95),
	PurpleLight = Color3.fromRGB(190, 150, 255),
	Ecto = Color3.fromRGB(110, 255, 120), -- Ectoplasm green
	EctoDark = Color3.fromRGB(30, 120, 60),
	Orange = Color3.fromRGB(255, 150, 40),
	Candy = Color3.fromRGB(255, 120, 200),
	Gem = Color3.fromRGB(120, 220, 255),
	White = Color3.fromRGB(255, 255, 255),
	Ink = Color3.fromRGB(25, 15, 40), -- text stroke / outlines
	Success = Color3.fromRGB(90, 220, 110),
	Error = Color3.fromRGB(255, 90, 110),
	Info = Color3.fromRGB(150, 120, 255),
}

Theme.Fonts = {
	Display = Enum.Font.LuckiestGuy, -- big titles, popups
	Body = Enum.Font.FredokaOne, -- everything else
}

Theme.CornerRadius = UDim.new(0.3, 0)

Theme.CurrencyIcons = {
	Ectoplasm = "💚",
	Candy = "🍬",
	SoulGems = "💎",
}

return Theme
