--!nocheck
-- Test runner: `lune run tests/run` from the haunted-brainrot folder.
-- Runs every tests/specs/*.spec.luau file; exits non-zero on any failure.

local fs = require("@lune/fs")
local process = require("@lune/process")
local TestKit = require("./harness/TestKit")

local filter = process.args[1]
local files = {}
for _, f in fs.readDir("tests/specs") do
	if f:match("%.spec%.luau$") and (not filter or f:find(filter, 1, true)) then
		table.insert(files, f)
	end
end
table.sort(files)

for _, f in files do
	print(`\n{f}`)
	local spec = require(`./specs/{f:gsub("%.luau$", "")}`)
	if type(spec) == "function" then
		spec(TestKit)
	end
end

local r = TestKit.results
print(`\n{r.passed} passed, {r.failed} failed`)
if r.failed > 0 then
	for _, f in r.failures do
		print(`FAILED: {f.name}`)
	end
	process.exit(1)
end
