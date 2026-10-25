--!nocheck
-- Minimal describe/it/expect test kit for Lune.

local TestKit = { results = { passed = 0, failed = 0, failures = {} } }

local currentSuite = ""

function TestKit.describe(name, fn)
	local prev = currentSuite
	currentSuite = if prev == "" then name else `{prev} > {name}`
	fn()
	currentSuite = prev
end

function TestKit.it(name, fn)
	local full = `{currentSuite} > {name}`
	local ok, err = xpcall(fn, function(e)
		return tostring(e) .. "\n" .. debug.traceback(nil, 2)
	end)
	if ok then
		TestKit.results.passed += 1
		print(`  \27[32m✓\27[0m {full}`)
	else
		TestKit.results.failed += 1
		table.insert(TestKit.results.failures, { name = full, err = err })
		print(`  \27[31m✗ {full}\27[0m\n    {err}`)
	end
end

local function fmt(v)
	if type(v) == "string" then
		return `"{v}"`
	end
	return tostring(v)
end

local function deepEqual(a, b)
	if type(a) ~= type(b) then
		return false
	end
	if type(a) ~= "table" then
		return a == b
	end
	for k, v in a do
		if not deepEqual(v, b[k]) then
			return false
		end
	end
	for k in b do
		if a[k] == nil then
			return false
		end
	end
	return true
end

function TestKit.expect(actual)
	local e = {}
	function e.toBe(expected)
		if actual ~= expected then
			error(`expected {fmt(expected)}, got {fmt(actual)}`, 2)
		end
	end
	function e.toEqual(expected)
		if not deepEqual(actual, expected) then
			error(`tables differ: expected {fmt(expected)}, got {fmt(actual)}`, 2)
		end
	end
	function e.toBeTruthy()
		if not actual then
			error(`expected truthy, got {fmt(actual)}`, 2)
		end
	end
	function e.toBeFalsy()
		if actual then
			error(`expected falsy, got {fmt(actual)}`, 2)
		end
	end
	function e.toBeNear(expected, eps)
		eps = eps or 1e-6
		if type(actual) ~= "number" or math.abs(actual - expected) > eps then
			error(`expected ~{expected} (±{eps}), got {fmt(actual)}`, 2)
		end
	end
	function e.toBeGreaterThan(x)
		if not (actual > x) then
			error(`expected > {x}, got {fmt(actual)}`, 2)
		end
	end
	function e.toBeLessThan(x)
		if not (actual < x) then
			error(`expected < {x}, got {fmt(actual)}`, 2)
		end
	end
	function e.toContain(x)
		if type(actual) == "string" then
			if not string.find(actual, x, 1, true) then
				error(`expected {fmt(actual)} to contain {fmt(x)}`, 2)
			end
		elseif not table.find(actual, x) then
			error(`expected table to contain {fmt(x)}`, 2)
		end
	end
	function e.toThrow(pattern)
		local ok, err = pcall(actual)
		if ok then
			error("expected function to throw", 2)
		end
		if pattern and not string.find(tostring(err), pattern, 1, true) then
			error(`expected error containing {fmt(pattern)}, got {fmt(err)}`, 2)
		end
	end
	return e
end

return TestKit
