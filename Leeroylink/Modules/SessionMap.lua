-- SessionMap: where things happened, for the map in Leeroyzan.
--   * the route of every session: map and position every few seconds (compact strings)
--   * places of events: death, level-up, boss, rare kill, rare loot, gathering,
--     discoveries, accepted and finished quests, screenshots
--   * an index of the game's maps (names, parents, position of each zone on its continent)
--   * the quest log of the character (with objectives), finished quest IDs, last position
-- Everything lives in the saved variables; WoW writes them on logout and /reload.
local ADDON, LZ = ...
local T, P, C = LZ.T, LZ.P, LZ.C

local mod = LZ:NewModule("Map", {
	group = "link",
	title = { "Karte", "Map" },
	desc = {
		"Merkt sich deinen Laufweg und wo etwas passiert ist (Tode, Stufen, Bosse, seltene Beute, Sammelpunkte, Entdeckungen, Quests, Screenshots) und deine Questliste. Leeroyzan zeigt alles auf seiner Karte.",
		"Remembers your route and where things happened (deaths, levels, bosses, rare loot, gathering, discoveries, quests, screenshots) and your quest log. Leeroyzan shows it all on its map.",
	},
})

local I = LZ.SessionInternal or {}
local isSecret = _G.issecretvalue or function() return false end

local FORMAT = 1
local TICK = 3            -- seconds between two looks at the position
local STEP = 0.004        -- a new route point after this distance (share of the map width)
local IDLE = 60           -- ... or after this many seconds with a small move
local GAP = 120           -- a longer pause (loading screen, AFK) starts a new piece of the route
local MAX_POINTS = 8000   -- per session; above that the current piece is thinned out
local MAX_PINS = 400
local INDEX_FORMAT = 1
local INDEX_DAYS = 7

local rt = {}             -- runtime state: current route piece, last point
local ticker

local function session()
	local S = LZ.modules.Session
	return S and S.enabled and S.Current and S:Current() or nil
end

local function int4(v) return math.floor(v * 10000 + 0.5) end

-- map ID and position (0..1) of the player; position is nil in instances and when the client hides it
local function where()
	local M = _G.C_Map
	if not (M and M.GetBestMapForUnit) then return nil end
	local ok, map = pcall(M.GetBestMapForUnit, "player")
	if not ok or type(map) ~= "number" or isSecret(map) or map <= 0 then return nil end
	if not M.GetPlayerMapPosition then return map end
	local ok2, pos = pcall(M.GetPlayerMapPosition, map, "player")
	if not ok2 or type(pos) ~= "table" then return map end
	local x, y
	if pos.GetXY then
		local ok3, a, b = pcall(pos.GetXY, pos)
		if ok3 then x, y = a, b end
	else
		x, y = pos.x, pos.y
	end
	if type(x) ~= "number" or type(y) ~= "number" or isSecret(x) or isSecret(y) then return map end
	if x <= 0 and y <= 0 then return map end
	return map, x, y
end

local function mode()
	local function yes(v) return v and not isSecret(v) end
	if yes(_G.UnitOnTaxi and UnitOnTaxi("player")) then return "t" end
	if yes(_G.UnitIsDeadOrGhost and UnitIsDeadOrGhost("player")) then return "g" end
	return nil
end

----------------------------------------------------------------------
-- Route
----------------------------------------------------------------------
local function mapTable(s)
	local M = s.map
	if type(M) ~= "table" or M.v ~= FORMAT then
		M = { v = FORMAT, segs = {}, pins = {}, n = 0 }
		s.map = M
	end
	return M
end

-- writes the points of the current piece into its string (x,y,seconds since the point before;...)
local function flush()
	local seg = rt.seg
	if not seg or not rt.xs or #rt.xs == 0 then return end
	local out, last = {}, rt.t0
	for i = 1, #rt.xs do
		out[i] = string.format("%d,%d,%d", rt.xs[i], rt.ys[i], math.max(0, rt.ts[i] - last))
		last = rt.ts[i]
	end
	seg.d = (seg.d ~= "" and (seg.d .. ";") or "") .. table.concat(out, ";")
	rt.t0 = last
	rt.xs, rt.ys, rt.ts = {}, {}, {}
end

local function endPiece()
	flush()
	rt.seg, rt.last = nil, nil
end

-- every second point of the current piece goes (keeps the shape, halves the size)
local function thin(M)
	local xs, ys, ts = {}, {}, {}
	for i = 1, #rt.xs do
		if i % 2 == 1 or i == #rt.xs then
			xs[#xs + 1], ys[#ys + 1], ts[#ts + 1] = rt.xs[i], rt.ys[i], rt.ts[i]
		end
	end
	M.n = M.n - (#rt.xs - #xs)
	rt.xs, rt.ys, rt.ts = xs, ys, ts
end

local function addPoint(M, x, y, t)
	local n = #rt.xs + 1
	rt.xs[n], rt.ys[n], rt.ts[n] = int4(x), int4(y), t
	M.n = (M.n or 0) + 1
	rt.last = { x = x, y = y, t = t }
	if M.n > MAX_POINTS then
		if #rt.xs >= 50 then thin(M) else rt.full = true end
	end
end

local function tick()
	local s = session()
	if not s then return end
	local M = mapTable(s)
	if rt.full then return end
	local map, x, y = where()
	local t = math.floor(time())
	if not x then endPiece(); return end
	local k = mode()
	local seg = rt.seg
	if seg and (seg.m ~= map or seg.k ~= k or not rt.last or t - rt.last.t > GAP) then
		endPiece()
		seg = nil
	end
	if not seg then
		seg = { m = map, k = k, t = t, d = "" }
		M.segs[#M.segs + 1] = seg
		rt.seg, rt.t0 = seg, t
		rt.xs, rt.ys, rt.ts = {}, {}, {}
		addPoint(M, x, y, t)
		return
	end
	local dx, dy = x - rt.last.x, y - rt.last.y
	local d = math.sqrt(dx * dx + dy * dy)
	if d >= STEP or (t - rt.last.t >= IDLE and d >= STEP / 4) then addPoint(M, x, y, t) end
end

local function safeTick()
	local ok, err = pcall(tick)
	if not ok and not rt.errored then
		rt.errored = true      -- the first error of a login goes to the error log, silently
		local log = LZ.modules.ErrorLog
		if log and log.enabled and log.Record then
			pcall(log.Record, log, "Interface\\AddOns\\Leeroylink\\Modules\\SessionMap.lua (tick): " .. tostring(err),
				_G.debugstack and debugstack(2) or nil)
		end
	end
end

----------------------------------------------------------------------
-- Places (called by the session modules: I.mark("death", { by = ... }))
----------------------------------------------------------------------
local function push(list, e, max)
	list[#list + 1] = e
	while #list > max do table.remove(list, 1) end
end

function I.mark(kind, data)
	if not mod.enabled then return nil end
	local s = session()
	if not s then return nil end
	local M = mapTable(s)
	local map, x, y = where()
	if not map then return nil end
	local t = math.floor(time())
	local last = M.pins[#M.pins]
	-- several items from one herb or vein: one place
	if kind == "gather" and last and last.k == "gather" and t - last.t <= 5 and last.m == map then return last end
	local e = {}
	for key, v in pairs(data or {}) do
		if not isSecret(v) then e[key] = v end
	end
	e.k, e.m, e.t = kind, map, t
	if x then e.x, e.y = int4(x), int4(y) end
	if I.rt and I.rt.run and I.rt.run.name then e.inst = e.inst or I.rt.run.name end
	push(M.pins, e, MAX_PINS)
	return e
end

mod:Event("SCREENSHOT_SUCCEEDED", function() I.mark("shot") end)

----------------------------------------------------------------------
-- Map index: names and position of every map (once a week or after a patch)
----------------------------------------------------------------------
local function rect(child, parent)
	local M = _G.C_Map
	if not (M.GetMapRectOnMap and child and parent) then return nil end
	local ok, x1, x2, y1, y2 = pcall(M.GetMapRectOnMap, child, parent)
	if not ok or type(x1) ~= "number" or type(y2) ~= "number" or x2 <= x1 or y2 <= y1 then return nil end
	return { int4(x1), int4(x2), int4(y1), int4(y2) }
end

local function buildIndex()
	local M = _G.C_Map
	if not (M and M.GetMapInfo) then return nil end
	local maps = {}
	local function add(id)
		if type(id) ~= "number" or maps[id] then return nil end
		local ok, info = pcall(M.GetMapInfo, id)
		if not ok or type(info) ~= "table" or not info.name then return nil end
		local e = { n = info.name, ty = info.mapType, p = info.parentMapID }
		maps[id] = e
		return e
	end
	-- roots: the world map and everything above the player's map
	local roots = { 947 }
	local cur = where()
	local guard = 0
	while cur and guard < 10 do
		roots[#roots + 1] = cur
		local ok, info = pcall(M.GetMapInfo, cur)
		cur = ok and type(info) == "table" and info.parentMapID or nil
		if cur == 0 then cur = nil end
		guard = guard + 1
	end
	for _, root in ipairs(roots) do
		add(root)
		if M.GetMapChildrenInfo then
			local ok, kids = pcall(M.GetMapChildrenInfo, root, nil, true)
			if ok and type(kids) == "table" then
				for _, k in ipairs(kids) do
					if type(k) == "table" and k.mapID and not maps[k.mapID] then
						maps[k.mapID] = { n = k.name, ty = k.mapType, p = k.parentMapID }
					end
				end
			end
		end
	end
	-- continents on the world map, zones on their continent
	local WORLD, CONTINENT, ZONE = 1, 2, 3
	for id, e in pairs(maps) do
		if e.ty == ZONE or e.ty == CONTINENT then
			local want = (e.ty == ZONE) and CONTINENT or WORLD
			local up, g = e.p, 0
			while up and maps[up] and maps[up].ty ~= want and g < 6 do
				up, g = maps[up].p, g + 1
			end
			if up and maps[up] and maps[up].ty == want then
				e.on = up
				e.r = rect(id, up)
			end
		end
	end
	local n = 0
	for _ in pairs(maps) do n = n + 1 end
	if n == 0 then return nil end
	return { v = INDEX_FORMAT, at = math.floor(time()), interface = C.InterfaceVersion(), lang = _G.GetLocale and GetLocale() or nil,
		n = n, maps = maps }
end

local function updateIndex(force)
	local old = LZ.gdb.mapIndex
	local iface = C.InterfaceVersion()
	local locale = _G.GetLocale and GetLocale() or nil
	if not force and type(old) == "table" and old.v == INDEX_FORMAT and old.interface == iface and old.lang == locale
		and (time() - (old.at or 0)) < INDEX_DAYS * 86400 then
		return
	end
	local idx = buildIndex()
	if idx then LZ.gdb.mapIndex = idx end
end

----------------------------------------------------------------------
-- Quest log, finished quests, last position (for the quest layer in Leeroyzan)
----------------------------------------------------------------------
local function objectives(id, logIndex)
	local out = {}
	local QL = _G.C_QuestLog
	if QL and QL.GetQuestObjectives then
		local ok, list = pcall(QL.GetQuestObjectives, id)
		if ok and type(list) == "table" then
			for _, o in ipairs(list) do
				if type(o) == "table" and type(o.text) == "string" and not isSecret(o.text) then
					out[#out + 1] = { text = o.text, done = o.finished and true or nil, ty = o.type }
				end
			end
			return out
		end
	end
	if logIndex and _G.GetNumQuestLeaderBoards and _G.GetQuestLogLeaderBoard then
		local ok, n = pcall(GetNumQuestLeaderBoards, logIndex)
		for k = 1, (ok and tonumber(n) or 0) do
			local ok2, text, ty, done = pcall(GetQuestLogLeaderBoard, k, logIndex)
			if ok2 and type(text) == "string" then out[#out + 1] = { text = text, done = done and true or nil, ty = ty } end
		end
	end
	return out
end

local function questLog()
	local list = {}
	if not (_G.GetNumQuestLogEntries and _G.GetQuestLogTitle) then return list end
	local n = GetNumQuestLogEntries() or 0
	for i = 1, n do
		local title, level, _, isHeader, _, isComplete, _, id = GetQuestLogTitle(i)
		if not isHeader and type(id) == "number" and id > 0 then
			list[#list + 1] = { id = id, title = title, lvl = level,
				done = (isComplete == 1 or isComplete == true) or nil, failed = (isComplete == -1) or nil,
				o = objectives(id, i) }
		end
	end
	return list
end

local function finishedQuests()
	local ids
	local QL = _G.C_QuestLog
	if QL and QL.GetAllCompletedQuestIDs then
		local ok, v = pcall(QL.GetAllCompletedQuestIDs)
		if ok and type(v) == "table" then ids = v end
	end
	if not ids and _G.GetQuestsCompleted then
		local ok, v = pcall(GetQuestsCompleted)
		if ok and type(v) == "table" then
			ids = {}
			for id, yes in pairs(v) do if yes then ids[#ids + 1] = id end end
		end
	end
	if not ids then return nil end
	table.sort(ids)
	local parts = {}
	for i, id in ipairs(ids) do parts[i] = tostring(id) end
	return table.concat(parts, ",")
end

function mod:Export()
	if not LZ.char then return end
	local ok, list = pcall(questLog)
	if ok then LZ.char.questLog = { t = math.floor(time()), list = list } end
	local ok2, done = pcall(finishedQuests)
	if ok2 and done then LZ.char.questsDone = done end
	local map, x, y = where()
	if map then LZ.char.pos = { m = map, x = x and int4(x) or nil, y = y and int4(y) or nil, t = math.floor(time()) } end
end

----------------------------------------------------------------------
-- Lifecycle
----------------------------------------------------------------------
-- Leeroyzan imports every session right after logout; old sessions in the saved
-- variables keep their places but drop the route, so the file stays small.
local KEEP_ROUTES = 15

local function trimOldRoutes()
	local list = LZ.gdb.sessionLog
	if type(list) ~= "table" then return end
	for i = 1, #list - KEEP_ROUTES do
		local M = type(list[i]) == "table" and list[i].map
		if type(M) == "table" and M.segs and #M.segs > 0 then
			M.segs = {}
			M.trimmed = true
		end
	end
end

function mod:OnEnable()
	rt = {}
	pcall(trimOldRoutes)
	if _G.C_Timer and C_Timer.NewTicker then
		ticker = C_Timer.NewTicker(TICK, safeTick)
	end
	LZ.After(2, function()
		if mod.enabled then pcall(updateIndex) end
	end)
end

function mod:OnDisable()
	endPiece()
	if ticker then ticker:Cancel(); ticker = nil end
end

function mod:OnLogout()
	endPiece()
	self:Export()
end

-- for tests and the report
function mod:Flush() flush() end
function mod:UpdateIndex(force) updateIndex(force) end

mod:Command({ "karte", "map" }, function(self, rest)
	if rest == "index" then
		updateIndex(true)
		local idx = LZ.gdb.mapIndex
		self:Print(string.format(T("%d Karten neu eingelesen.", "%d maps read again."), idx and idx.n or 0))
		return
	end
	local map, x, y = where()
	if not map then self:Print(T("Keine Position verfügbar.", "No position available.")); return end
	local s = session()
	local M = s and s.map
	self:Print(string.format("%s %d%s · %s", T("Karte", "Map"), map,
		x and string.format(" · %.1f, %.1f", x * 100, y * 100) or "",
		M and string.format(T("%d Wegpunkte, %d Orte in dieser Sitzung", "%d route points, %d places this session"),
			M.n or 0, #M.pins) or T("keine Sitzung", "no session")))
end, { "/lz karte", "Position und Kartenaufzeichnung dieser Sitzung", "position and map recording of this session" })

function mod:Summary()
	local s = session()
	local M = s and s.map
	if not M then return T("Noch keine Wegpunkte", "No route yet") end
	return string.format(T("%d Wegpunkte · %d Orte", "%d route points · %d places"), M.n or 0, #M.pins)
end

function mod:Report()
	local s = session()
	local M = s and s.map
	local lines = {}
	if not M then
		lines[1] = T("Diese Sitzung hat noch keine Wegpunkte.", "This session has no route yet.")
	else
		lines[#lines + 1] = string.format(T("Wegpunkte: %d in %d Abschnitten", "Route points: %d in %d pieces"), M.n or 0, #M.segs)
		local kinds = {}
		for _, p in ipairs(M.pins) do kinds[p.k] = (kinds[p.k] or 0) + 1 end
		local names = { death = { "Tode", "Deaths" }, level = { "Stufen", "Levels" }, boss = { "Bosse", "Bosses" },
			rare = { "Seltene Gegner", "Rare enemies" }, loot = { "Seltene Beute", "Rare loot" },
			gather = { "Sammelpunkte", "Gathering" }, found = { "Entdeckt", "Discovered" },
			qa = { "Quests angenommen", "Quests accepted" }, qd = { "Quests abgegeben", "Quests turned in" },
			shot = { "Screenshots", "Screenshots" } }
		for k, n in pairs(kinds) do
			lines[#lines + 1] = string.format("%s: %d", names[k] and P(names[k]) or k, n)
		end
	end
	local idx = LZ.gdb.mapIndex
	lines[#lines + 1] = ""
	lines[#lines + 1] = string.format(T("Karten im Verzeichnis: %d", "Maps in the index: %d"), idx and idx.n or 0)
	lines[#lines + 1] = T("Leeroyzan zeigt alles auf der Seite „Karte“.", "Leeroyzan shows everything on its \"Map\" page.")
	return table.concat(lines, "\n")
end
