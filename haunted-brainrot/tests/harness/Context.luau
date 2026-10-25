--!nocheck
-- Builds a Loader wired to the project's folder mapping plus default mocks.

local process = require("@lune/process")
local Loader = require("./Loader")
local Mocks = require("./Mocks")
local Shim = require("./Shim")
Shim.install()

local Context = {}

Context.Services = {
	ReplicatedStorage = "src/ReplicatedStorage",
	ServerScriptService = "src/ServerScriptService",
	ServerStorage = "src/ServerStorage",
}

function Context.new(opts)
	opts = opts or {}
	local cloud = opts.cloud or Mocks.DataStoreCloud()
	local players = opts.players or Mocks.Players()
	local mocks = {
		Players = players,
		RunService = Mocks.RunService({ server = opts.server, studio = opts.studio }),
		DataStoreService = Mocks.DataStoreService(cloud),
		TextService = Mocks.TextService(),
	}
	for k, v in opts.mocks or {} do
		mocks[k] = v
	end
	-- Long waits (autosave / game loops) park forever so Lune can exit; tests call the work directly.
	local realTask = require("@lune/task")
	local testTask = setmetatable({
		wait = function(s)
			if s and s >= (opts.parkWaitsOver or 20) then
				coroutine.yield()
			end
			return realTask.wait(s)
		end,
	}, { __index = realTask })
	local globals = { task = testTask }
	for k, v in opts.globals or {} do
		globals[k] = v
	end
	local ctx = Loader.new({
		root = process.cwd,
		services = Context.Services,
		mocks = mocks,
		jobId = opts.jobId,
		quiet = opts.quiet,
		globals = globals,
	})
	ctx.cloud = cloud
	ctx.players = players
	ctx.mocks = mocks
	return ctx
end

return Context
