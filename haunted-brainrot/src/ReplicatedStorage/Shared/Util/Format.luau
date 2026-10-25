--!strict
-- Number and time formatting for HUD counters and popups ("1.2K", "3.45M", "1:05").

local Format = {}

local SUFFIXES = { "", "K", "M", "B", "T", "Qa", "Qi", "Sx", "Sp", "Oc", "No", "Dc" }

-- Abbreviates a number: 950 -> "950", 1234 -> "1.23K", 15300 -> "15.3K", 2.5e6 -> "2.5M".
function Format.Abbreviate(n: number): string
	if n ~= n then
		return "0"
	end
	local negative = n < 0
	n = math.abs(n)
	if n < 1000 then
		local s = if n == math.floor(n) then tostring(math.floor(n)) else string.format("%.1f", n)
		s = s:gsub("%.0$", "")
		return (if negative then "-" else "") .. s
	end
	local tier = math.min(math.floor(math.log10(n) / 3), #SUFFIXES - 1)
	local scaled = n / 10 ^ (tier * 3)
	-- Avoid "1000K": round first, bump tier if needed.
	local decimals = if scaled < 10 then 2 elseif scaled < 100 then 1 else 0
	local rounded = math.floor(scaled * 10 ^ decimals + 0.5) / 10 ^ decimals
	if rounded >= 1000 and tier < #SUFFIXES - 1 then
		tier += 1
		rounded = rounded / 1000
		decimals = 2
	end
	local s = string.format(`%.{decimals}f`, rounded)
	s = s:gsub("%.?0+$", "")
	return (if negative then "-" else "") .. s .. SUFFIXES[tier + 1]
end

-- "+💚 1.2K" style income/currency popups.
function Format.Ectoplasm(n: number): string
	return "💚 " .. Format.Abbreviate(n)
end

function Format.PerSecond(n: number): string
	return Format.Abbreviate(n) .. "/s"
end

-- Seconds -> "m:ss" (or "h:mm:ss").
function Format.Time(seconds: number): string
	seconds = math.max(0, math.floor(seconds))
	local h = seconds // 3600
	local m = (seconds % 3600) // 60
	local s = seconds % 60
	if h > 0 then
		return string.format("%d:%02d:%02d", h, m, s)
	end
	return string.format("%d:%02d", m, s)
end

-- Adds thousands separators: 1234567 -> "1,234,567".
function Format.Commas(n: number): string
	local s = tostring(math.floor(n))
	local negative = s:sub(1, 1) == "-"
	if negative then
		s = s:sub(2)
	end
	local out = s:reverse():gsub("(%d%d%d)", "%1,"):reverse()
	out = out:gsub("^,", "")
	return (if negative then "-" else "") .. out
end

return Format
