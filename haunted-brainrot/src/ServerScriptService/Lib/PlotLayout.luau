--!strict
--[[
	PlotLayout
	Where the plots sit: GameConfig.Plots.count plots evenly spaced on a ring around the plaza.
	Each plot's CFrame is at ground level with its LookVector pointing at the plaza centre, so in a
	plot's local space -Z is "towards the plaza" (the mansion's front door side).
]]

local GameConfig = require(game:GetService("ReplicatedStorage").Shared.Config.GameConfig)

local PlotLayout = {}

PlotLayout.Center = Vector3.new(0, GameConfig.Plots.groundY, 0)

function PlotLayout.PlotCFrame(index: number): CFrame
	local cfg = GameConfig.Plots
	local angle = (index - 1) * (2 * math.pi / cfg.count)
	local position = Vector3.new(math.sin(angle) * cfg.ringRadius, cfg.groundY, math.cos(angle) * cfg.ringRadius)
	return CFrame.lookAt(position, PlotLayout.Center)
end

function PlotLayout.All(): { CFrame }
	local out = {}
	for i = 1, GameConfig.Plots.count do
		out[i] = PlotLayout.PlotCFrame(i)
	end
	return out
end

-- True if a world position is inside plot `index`'s footprint (any height).
function PlotLayout.Contains(index: number, position: Vector3, margin: number?): boolean
	local cfg = GameConfig.Plots
	local localPos = PlotLayout.PlotCFrame(index):PointToObjectSpace(position)
	local m = margin or 0
	return math.abs(localPos.X) <= cfg.plotSize.X / 2 + m and math.abs(localPos.Z) <= cfg.plotSize.Z / 2 + m
end

-- Index of the plot containing `position`, or nil.
function PlotLayout.PlotAt(position: Vector3): number?
	for i = 1, GameConfig.Plots.count do
		if PlotLayout.Contains(i, position) then
			return i
		end
	end
	return nil
end

return PlotLayout
