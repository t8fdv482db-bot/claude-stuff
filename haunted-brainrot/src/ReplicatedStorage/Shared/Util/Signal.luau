--!strict
-- Minimal pure-Luau signal (no BindableEvent), safe to use from any module.

export type Connection = {
	Connected: boolean,
	Disconnect: (self: Connection) -> (),
}

export type Signal<T...> = {
	Connect: (self: Signal<T...>, fn: (T...) -> ()) -> Connection,
	Once: (self: Signal<T...>, fn: (T...) -> ()) -> Connection,
	Fire: (self: Signal<T...>, T...) -> (),
	Wait: (self: Signal<T...>) -> T...,
	DisconnectAll: (self: Signal<T...>) -> (),
}

local Signal = {}
Signal.__index = Signal

function Signal.new<T...>(): Signal<T...>
	local self = setmetatable({ _handlers = {} :: { any } }, Signal)
	return (self :: any) :: Signal<T...>
end

function Signal:Connect(fn)
	local handlers = self._handlers
	local connection
	connection = {
		Connected = true,
		_fn = fn,
		Disconnect = function(c)
			if not c.Connected then
				return
			end
			c.Connected = false
			local i = table.find(handlers, c)
			if i then
				table.remove(handlers, i)
			end
		end,
	}
	table.insert(handlers, connection)
	return connection
end

function Signal:Once(fn)
	local connection
	connection = self:Connect(function(...)
		connection:Disconnect()
		fn(...)
	end)
	return connection
end

function Signal:Fire(...)
	-- Copy so handlers can disconnect while firing.
	for _, c in table.clone(self._handlers) do
		if c.Connected then
			task.spawn(c._fn, ...)
		end
	end
end

function Signal:Wait()
	local thread = coroutine.running()
	self:Once(function(...)
		task.spawn(thread, ...)
	end)
	return coroutine.yield()
end

function Signal:DisconnectAll()
	for _, c in table.clone(self._handlers) do
		c:Disconnect()
	end
end

return Signal
