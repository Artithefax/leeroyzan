-- LayerHop: switch to the layer of a friend or guild mate.
--
-- Since the hotfix of 2026-11-20 WoW Forever hides from addons which layer you are on (the realm part of
-- NPC GUIDs is scrambled, GetRealmName() returns ""), on purpose: no addon can send you to "layer 3" any
-- more, and this one does not try. What still works is the game's own rule: whoever joins a group moves
-- to the layer of its members and keeps it after leaving. So Leeroylink asks the other player's Leeroylink
-- for an invite (a hidden addon message to a friend, a Battle.net friend or a guild mate), accepts it,
-- waits a few seconds and leaves the group again. The other side decides: by default a popup asks first.
--
-- Messages (prefix "Leeroylink", fields separated by ";"):
--   LH1;PING                       who has Leeroylink?           -> LH1;PONG;<version>;<hosts 1/0>;<zone map>
--   LH1;REQ;<zone map>;<character> please invite me            -> LH1;ACK;<zone map>  (asking the player)
--                                                                  LH1;INV;<zone map>  (invite sent)
--                                                                  LH1;NO;<reason>
local ADDON, LZ = ...
local T, P = LZ.T, LZ.P

local PREFIX, VER, SEP = "Leeroylink", "LH1", ";"
local ASK_TIMEOUT, WAIT_TIMEOUT, HOST_TIMEOUT = 10, 45, 30
local MIN_GAP, PING_GAP = 15, 30

local mod = LZ:NewModule("LayerHop", {
	title = { "Layerwechsel", "Layer switch" },
	desc = {
		"Auf den Layer eines Freundes oder Gildenmitglieds wechseln: dessen Leeroylink lädt dich ein, du nimmst an und verlässt die Gruppe ein paar Sekunden später wieder. Einen bestimmten Layer (1, 2, 3 …) wählen geht in WoW Forever seit dem Hotfix vom 20.11.2026 nicht mehr – Blizzard verbirgt den Layer vor Addons.",
		"Switch to the layer of a friend or guild mate: their Leeroylink invites you, you accept and leave the group again a few seconds later. Picking a numbered layer (1, 2, 3 …) is no longer possible in WoW Forever since the hotfix of Nov 20, 2026 – Blizzard hides the layer from addons.",
	},
	defaults = { autoAccept = true, autoLeave = true, host = true, autoInvite = false, leaveDelay = 6 },
	options = {
		{ key = "autoAccept", label = { "Einladung des gewählten Spielers automatisch annehmen", "Accept the invite of the chosen player automatically" } },
		{ key = "autoLeave", label = { "Danach die Gruppe von selbst verlassen (Wartezeit: /lz layer warten <Sek.>)", "Leave the group by itself afterwards (delay: /lz layer wait <sec>)" } },
		{ key = "host", label = { "Freunde und Gilde dürfen auf meinen Layer wechseln (Leeroylink fragt mich)", "Friends and guild may switch to my layer (Leeroylink asks me)" } },
		{ key = "autoInvite", label = { "… ohne Nachfrage einladen", "… invite them without asking" } },
	},
})

----------------------------------------------------------------------
-- Defensive access to the game: a missing or changed function returns nil instead of an error
----------------------------------------------------------------------
local function pass(ok, ...) if ok then return ... end end
local function call(f, ...) if type(f) == "function" then return pass(pcall(f, ...)) end end
local function try(f, ...) if type(f) ~= "function" then return false end return (pcall(f, ...)) end
local function G(name) return _G[name] end
local function NS(ns, name) local t = _G[ns]; return type(t) == "table" and t[name] or nil end

local function base(name)
	if type(name) ~= "string" or name == "" then return nil end
	return name:match("^([^%-]+)") or name
end
local function lkey(name) local b = base(name); return b and b:lower() end
local function myName() return (call(G("UnitName"), "player")) end

local function inInstance()
	local inside, kind = call(G("IsInInstance"))
	return (inside and kind ~= "none") and true or false
end

local function inCombat()
	return (call(G("InCombatLockdown")) or call(G("UnitAffectingCombat"), "player")) and true or false
end

local function inGroup()
	local f = G("IsInGroup")
	if f then return call(f) and true or false end
	return (tonumber((call(G("GetNumGroupMembers")))) or 0) > 0
end
local function inRaid() return call(G("IsInRaid")) and true or false end
local function groupSize() return tonumber((call(G("GetNumGroupMembers")))) or 0 end
local function canInvite()
	if not inGroup() then return true end
	if call(G("UnitIsGroupLeader"), "player") then return true end
	return inRaid() and call(G("UnitIsGroupAssistant"), "player") and true or false
end

-- true and the unit when this player is in my group
local function groupHas(name)
	local k = lkey(name)
	if not k or not inGroup() then return false end
	local raid = inRaid()
	for i = 1, raid and 40 or 4 do
		local unit = (raid and "raid" or "party") .. i
		if lkey((call(G("UnitName"), unit))) == k then return true, unit end
	end
	return false
end

-- the zone map a unit is in (cities count as zones, caves and buildings belong to their zone)
local ZONE_TYPE = 3
local function zoneMap(unit)
	local M = _G.C_Map
	if type(M) ~= "table" then return nil end
	local id = call(M.GetBestMapForUnit, unit or "player")
	for _ = 1, 8 do
		if type(id) ~= "number" or id <= 0 then return nil end
		local info = call(M.GetMapInfo, id)
		if type(info) ~= "table" or not info.mapType or info.mapType <= ZONE_TYPE then return id end
		id = info.parentMapID
	end
	return id
end

local function mapName(id)
	local M = _G.C_Map
	local info = type(M) == "table" and type(id) == "number" and call(M.GetMapInfo, id)
	return type(info) == "table" and info.name or T("unbekannt", "unknown")
end

local function zoneText()
	local z = call(G("GetRealZoneText")) or call(G("GetZoneText"))
	return type(z) == "string" and z ~= "" and z or nil
end

----------------------------------------------------------------------
-- Messages
----------------------------------------------------------------------
local function encode(...)
	local parts = { VER }
	for i = 1, select("#", ...) do parts[#parts + 1] = tostring((select(i, ...))) end
	return table.concat(parts, SEP)
end

local function sendRaw(chatType, target, msg)
	local CI = _G.C_ChatInfo
	local f = (type(CI) == "table" and CI.SendAddonMessage) or G("SendAddonMessage")
	if type(f) ~= "function" then return false end
	local ok, res = pcall(f, PREFIX, msg, chatType, target)
	if not ok then return false end
	if type(res) == "number" then return res == 0 end   -- newer clients: Enum.SendAddonMessageResult, 0 = success
	return res ~= false
end

-- target: { name = "Name" or "Name-Realm", bnet = gameAccountID }
local function send(target, ...)
	if type(target) ~= "table" or inInstance() then return false end   -- no addon messages in instances
	local msg = encode(...)
	if target.bnet and try(G("BNSendGameData"), target.bnet, PREFIX, msg) then return true end
	if target.full or target.name then return sendRaw("WHISPER", target.full or target.name, msg) end
	return false
end

local function sendGuild(...)
	if inInstance() or not call(G("IsInGuild")) then return false end
	return sendRaw("GUILD", nil, encode(...))
end

----------------------------------------------------------------------
-- Who could I switch to: Battle.net friends in this game, friends, guild mates (online)
----------------------------------------------------------------------
local cands, byKey, scannedAt = {}, {}, -100
local seen = {}          -- [key] = { v = version, h = hosts, map = zone map, t = time } – they have Leeroylink
local rq = { state = "idle", token = 0, last = 0 }   -- my own switch
local host = {}          -- host.pending = a request to me
local lastPing = -100

local VIA = { bnet = { "Battle.net", "Battle.net" }, friend = { "Freund", "friend" }, guild = { "Gilde", "guild" } }

local function bnetGames(i)
	local BN = _G.C_BattleNet
	local out = {}
	if type(BN) ~= "table" then return out end
	local n = tonumber((call(BN.GetFriendNumGameAccounts, i))) or 0
	for j = 1, math.min(n, 10) do
		local ga = call(BN.GetFriendGameAccountInfo, i, j)
		if type(ga) == "table" then out[#out + 1] = ga end
	end
	if #out == 0 then
		local acc = call(BN.GetFriendAccountInfo, i)
		if type(acc) == "table" and type(acc.gameAccountInfo) == "table" then out[1] = acc.gameAccountInfo end
	end
	return out
end

local function sameGame(ga, faction)
	if ga.isOnline == false then return false end
	if ga.clientProgram and ga.clientProgram ~= (_G.BNET_CLIENT_WOW or "WoW") then return false end
	if type(ga.characterName) ~= "string" or ga.characterName == "" then return false end
	local project = _G.WOW_PROJECT_ID
	if ga.wowProjectID and project and ga.wowProjectID ~= project then return false end
	if ga.factionName and faction and ga.factionName ~= faction then return false end
	return true
end

function mod:Scan(force)
	local now = time()
	if not force and now - scannedAt < 3 then return cands end
	scannedAt = now
	local list, keys = {}, {}
	local me = lkey(myName())
	local here = zoneText()
	local function add(e)
		e.key = lkey(e.name)
		if not e.key or e.key == me then return end
		if type(e.full) == "string" then e.full = e.full:gsub("%-$", "") end
		local old = keys[e.key]
		if old then
			old.bnet = old.bnet or e.bnet
			old.account = old.account or e.account
			if not old.zone or old.zone == "" then old.zone = e.zone end
			old.via[#old.via + 1] = e.via[1]
			return
		end
		keys[e.key] = e
		list[#list + 1] = e
	end

	local faction = call(G("UnitFactionGroup"), "player")
	local numBN = tonumber((call(G("BNGetNumFriends")))) or 0
	local BN = _G.C_BattleNet
	for i = 1, math.min(numBN, 300) do
		local acc = type(BN) == "table" and call(BN.GetFriendAccountInfo, i)
		for _, ga in ipairs(bnetGames(i)) do
			if sameGame(ga, faction) then
				add({ name = base(ga.characterName), full = ga.characterName, zone = ga.areaName, level = ga.characterLevel,
					class = ga.className, bnet = ga.gameAccountID,
					account = type(acc) == "table" and (acc.accountName or acc.battleTag) or nil, via = { "bnet" } })
			end
		end
	end

	local FL = _G.C_FriendList
	if type(FL) == "table" and FL.GetNumFriends then
		local n = tonumber((call(FL.GetNumFriends))) or 0
		for i = 1, math.min(n, 300) do
			local f = call(FL.GetFriendInfoByIndex, i)
			if type(f) == "table" and f.connected and f.name then
				add({ name = base(f.name), full = f.name, zone = f.area, level = f.level, class = f.className, via = { "friend" } })
			end
		end
	end

	if call(G("IsInGuild")) then
		local n = tonumber((call(G("GetNumGuildMembers")))) or 0
		for i = 1, math.min(n, 1000) do
			local name, _, _, level, _, zone, _, _, online, _, class = call(G("GetGuildRosterInfo"), i)
			if name and online then add({ name = base(name), full = name, zone = zone, level = level, class = class, via = { "guild" } }) end
		end
	end

	for _, e in ipairs(list) do
		e.here = here ~= nil and e.zone == here
		e.inGroup = groupHas(e.full or e.name)
		e.lz = seen[e.key]
	end
	table.sort(list, function(a, b)
		if a.here ~= b.here then return a.here end
		if (a.lz ~= nil) ~= (b.lz ~= nil) then return a.lz ~= nil end
		return a.key < b.key
	end)
	cands, byKey = list, keys
	return list
end

-- friends, Battle.net friends and guild mates may ask me
local function allowed(from)
	if from.bnet then return true end
	local k = lkey(from.name)
	if not k then return false end
	if not byKey[k] then mod:Scan(true) end
	return byKey[k] ~= nil
end

function mod:Find(text)
	local want = LZ.Trim(text):lower()
	if want == "" then return nil end
	local list = self:Scan(true)
	for _, c in ipairs(list) do if c.key == want then return c end end
	for _, c in ipairs(list) do if c.key:sub(1, #want) == want then return c end end
	for _, c in ipairs(list) do
		if type(c.account) == "string" and c.account:lower():sub(1, #want) == want then return c end
	end
end

function mod:Ping(force)
	if inInstance() then return end
	if not force and time() - lastPing < PING_GAP then return end
	lastPing = time()
	for _, c in ipairs(self:Scan(true)) do
		local friend = c.bnet ~= nil
		for _, v in ipairs(c.via) do if v == "friend" then friend = true end end
		if friend then send(c, "PING") end
	end
	sendGuild("PING")
end

----------------------------------------------------------------------
-- My switch: ask -> wait for the invite -> accept -> in the group -> leave
----------------------------------------------------------------------
local refreshWindow   -- set below

local function resetRq()
	rq = { state = "idle", token = rq.token + 1, last = rq.last }
	if refreshWindow then refreshWindow() end
end

local function after(sec, state, fn)
	local tok = rq.token
	LZ.After(sec, function()
		if mod.enabled and rq.token == tok and rq.state == state then LZ:Safe(fn) end
	end)
end

local function setState(state)
	rq.state = state
	rq.token = rq.token + 1
	if refreshWindow then refreshWindow() end
end

local function hidePartyInvite()
	local find = G("StaticPopup_FindVisible")
	local dlg = find and call(find, "PARTY_INVITE")
	if type(dlg) == "table" then dlg.inviteAccepted = 1 end
	for i = 1, tonumber(_G.STATICPOPUP_NUMDIALOGS) or 4 do
		local d = _G["StaticPopup" .. i]
		if type(d) == "table" and d.which == "PARTY_INVITE" then d.inviteAccepted = 1 end
	end
	try(G("StaticPopup_Hide"), "PARTY_INVITE")
end

local function targetName() return rq.target and (rq.target.name or "?") or "?" end

-- the other side answered or invited: wait for the invite (longer while the game's invite popup is open)
local function toWaiting()
	if rq.state ~= "asking" then return end
	setState("waiting")
	local function timeout()
		if rq.invitedAt and not rq.extended then
			rq.extended = true
			after(60, "waiting", timeout)
			return
		end
		mod:Print(string.format(T("Keine Einladung von %s gekommen.", "No invite from %s."), targetName()))
		resetRq()
	end
	after(WAIT_TIMEOUT, "waiting", timeout)
end

function mod:Hop(c)
	if type(c) ~= "table" then return false end
	if rq.state ~= "idle" then
		self:Print(string.format(T("Läuft schon: Wechsel zu %s. Abbrechen: /lz layer stop", "Already running: switching to %s. Cancel: /lz layer stop"), targetName()))
		return false
	end
	if inInstance() then self:Print(T("In Instanzen gibt es keine Layer.", "Instances have no layers.")) return false end
	if inCombat() then self:Print(T("Nicht im Kampf – danach nochmal.", "Not in combat – try again afterwards.")) return false end
	if c.inGroup or groupHas(c.full or c.name) then
		self:Print(string.format(T("Du bist schon mit %s in einer Gruppe – also auf demselben Layer.", "You are already in a group with %s – so on the same layer."), c.name))
		return false
	end
	if inGroup() then
		self:Print(T("Du bist in einer Gruppe. Verlass sie zuerst – eine Einladung lässt sich nur ohne Gruppe annehmen.",
			"You are in a group. Leave it first – an invite can only be accepted without a group."))
		return false
	end
	local wait = MIN_GAP - (time() - rq.last)
	if wait > 0 then
		self:Print(string.format(T("Kurz warten (%d s), dann nochmal.", "Wait a moment (%d s), then try again."), wait))
		return false
	end
	rq.last = time()
	rq.target, rq.hostMap, rq.invitedAt, rq.waitZone, rq.leaveAt = c, nil, nil, nil, nil
	if not send(c, "REQ", zoneMap() or 0, myName() or "") then
		self:Print(string.format(T("%s ist gerade nicht erreichbar.", "%s cannot be reached right now."), c.name))
		resetRq()
		return false
	end
	setState("asking")
	self:Print(string.format(T("Frage %s nach einer Einladung …", "Asking %s for an invite …"), c.name))
	if c.zone and zoneText() and c.zone ~= zoneText() then
		self:Print(string.format(T("%s ist in einer anderen Zone (%s) – der Layer wechselt erst, wenn du dort bist.", "%s is in another zone (%s) – the layer changes once you are there."), c.name, c.zone))
	end
	after(ASK_TIMEOUT, "asking", function()
		mod:Print(string.format(T("%s antwortet nicht. Braucht Leeroylink 0.11 oder neuer – oder lädt dich einfach selbst ein.",
			"%s does not answer. Needs Leeroylink 0.11 or newer – or can simply invite you by hand."), targetName()))
		resetRq()
	end)
	return true
end

function mod:Cancel(quiet)
	if rq.state == "idle" then return false end
	if rq.state == "joined" then
		if not quiet then self:Print(T("Du bleibst in der Gruppe. Verlassen: /lz layer verlassen", "You stay in the group. Leave: /lz layer leave")) end
		rq.target.keep = true
		rq.waitZone, rq.leaveAt = nil, nil
		rq.token = rq.token + 1
		if refreshWindow then refreshWindow() end
		return true
	end
	if not quiet then self:Print(T("Layerwechsel abgebrochen.", "Layer switch cancelled.")) end
	resetRq()
	return true
end

-- leaves only a group that was joined for a switch – never the player's own group
function mod:Leave()
	if rq.state ~= "joined" then
		self:Print(T("Leeroylink verlässt nur eine Gruppe, die es für einen Layerwechsel betreten hat.",
			"Leeroylink only leaves a group it joined for a layer switch."))
		return false
	end
	local name = targetName()
	resetRq()
	if not inGroup() then return true end
	local PI = _G.C_PartyInfo
	local ok = (type(PI) == "table" and try(PI.LeaveParty)) or try(G("LeaveParty"))
	if ok then
		self:Print(string.format(T("Gruppe verlassen – du bist jetzt auf dem Layer von %s. Hat sich nichts geändert, lässt Blizzard gerade keinen Wechsel zu: in ein paar Minuten nochmal versuchen.",
			"Left the group – you are on %s's layer now. If nothing changed, Blizzard does not allow a switch right now: try again in a few minutes."), name))
	else
		self:Print(T("Konnte die Gruppe nicht verlassen – bitte selbst verlassen.", "Could not leave the group – please leave it yourself."))
	end
	return ok
end

local function delay()
	local d = tonumber(mod.opt.leaveDelay) or 6
	return math.max(2, math.min(60, math.floor(d)))
end

function mod:PlanLeave()
	if rq.state ~= "joined" or (rq.target and rq.target.keep) then return end
	rq.token = rq.token + 1                 -- replaces a leave planned before
	rq.leaveAt, rq.waitZone = nil, nil
	if not self.opt.autoLeave then
		if not rq.toldStay then
			rq.toldStay = true
			self:Print(string.format(T("Du bist in der Gruppe von %s und wechselst auf diesen Layer. Verlassen: /lz layer verlassen",
				"You are in %s's group and move to their layer. Leave: /lz layer leave"), targetName()))
		end
		return
	end
	local mine, theirs = zoneMap(), rq.hostMap
	if not theirs and rq.target then
		local _, unit = groupHas(rq.target.full or rq.target.name)
		theirs = unit and zoneMap(unit)
	end
	if theirs and theirs > 0 and mine and mine ~= theirs then
		rq.waitZone = theirs
		if rq.toldZone ~= theirs then
			rq.toldZone = theirs
			self:Print(string.format(T("%s ist in einer anderen Zone (%s). Der Layer wechselt erst, wenn du dort ankommst – dann verlässt Leeroylink die Gruppe von selbst.",
				"%s is in another zone (%s). The layer changes once you arrive there – then Leeroylink leaves the group by itself."), targetName(), mapName(theirs)))
		end
		if refreshWindow then refreshWindow() end
		return
	end
	if inCombat() then
		rq.afterCombat = true
		self:Print(T("Erst nach dem Kampf geht es weiter.", "Continuing after combat."))
		return
	end
	rq.afterCombat = nil
	local d = delay()
	rq.leaveAt = time() + d
	self:Print(string.format(T("In der Gruppe von %s – du wechselst auf diesen Layer, Leeroylink verlässt die Gruppe in %d s.",
		"In %s's group – you move to their layer, Leeroylink leaves the group in %d s."), targetName(), d))
	if refreshWindow then refreshWindow() end
	after(d, "joined", function()
		if inCombat() then rq.afterCombat = true; rq.leaveAt = nil; return end
		mod:Leave()
	end)
end

function mod:CheckGroup()
	if (rq.state == "asking" or rq.state == "waiting") and rq.invitedAt and inGroup() then
		hidePartyInvite()
		setState("joined")
		rq.joinedAt = time()
		self:PlanLeave()
	elseif rq.state == "joined" and not inGroup() then
		self:Print(string.format(T("Gruppe beendet – normalerweise bist du jetzt auf dem Layer von %s.", "Group ended – normally you are on %s's layer now."), targetName()))
		resetRq()
	end
	if refreshWindow then refreshWindow() end
end

mod:Event("PARTY_INVITE_REQUEST", function(self, _, inviter)
	if (rq.state ~= "asking" and rq.state ~= "waiting") or not rq.target then return end
	if lkey(inviter) ~= rq.target.key then return end
	rq.invitedAt = time()
	toWaiting()
	if not self.opt.autoAccept then
		self:Print(string.format(T("%s lädt dich ein – annehmen, dann landest du auf dem Layer von %s.", "%s invites you – accept to move to %s's layer."), rq.target.name, rq.target.name))
		return
	end
	-- the game's invite popup closes only once the group is joined (CheckGroup): hiding it right
	-- after AcceptGroup() can decline the invite instead
	try(G("AcceptGroup"))
	if inGroup() then self:CheckGroup() end
end)

mod:Event("GROUP_ROSTER_UPDATE", function(self) self:CheckGroup() end)
mod:Event("GROUP_LEFT", function(self) self:CheckGroup() end)

mod:Event("ZONE_CHANGED_NEW_AREA", function(self)
	if rq.state == "joined" and rq.waitZone and zoneMap() == rq.waitZone then
		rq.waitZone = nil
		self:PlanLeave()
	end
end)

mod:Event("PLAYER_REGEN_ENABLED", function(self)
	if rq.state == "joined" and rq.afterCombat then
		rq.afterCombat = nil
		self:PlanLeave()
	end
end)

----------------------------------------------------------------------
-- Someone asks me
----------------------------------------------------------------------
local function hideHostPopup() try(G("StaticPopup_Hide"), "LEEROYLINK_LAYERHOP") end

function mod:Invite()
	local p = host.pending
	if not p then return false end
	host.pending = nil
	hideHostPopup()
	local ok = false
	if p.from.bnet and G("BNInviteFriend") then ok = try(G("BNInviteFriend"), p.from.bnet) end
	if not ok then
		local name = p.from.name or p.name
		local PI = _G.C_PartyInfo
		ok = (type(PI) == "table" and try(PI.InviteUnit, name)) or try(G("InviteUnit"), name)
	end
	if ok then
		send(p.from, "INV", zoneMap() or 0)
		self:Print(string.format(T("%s eingeladen – wechselt auf deinen Layer und verlässt die Gruppe gleich wieder.",
			"Invited %s – they move to your layer and leave the group again shortly."), p.name))
	else
		send(p.from, "NO", "invite")
		self:Print(string.format(T("Konnte %s nicht einladen.", "Could not invite %s."), p.name))
	end
	return ok
end

function mod:Decline(quiet)
	local p = host.pending
	if not p then return false end
	host.pending = nil
	hideHostPopup()
	send(p.from, "NO", "declined")
	if not quiet then self:Print(string.format(T("Anfrage von %s abgelehnt.", "Declined %s's request."), p.name)) end
	return true
end

local function askHost(name)
	local D = _G.StaticPopupDialogs
	if type(D) ~= "table" or not G("StaticPopup_Show") then return false end
	D.LEEROYLINK_LAYERHOP = D.LEEROYLINK_LAYERHOP or {
		text = "%s",
		OnAccept = function() LZ:Safe(mod.Invite, mod) end,
		OnCancel = function() LZ:Safe(mod.Decline, mod, true) end,
		timeout = HOST_TIMEOUT, whileDead = 1, hideOnEscape = 1, preferredIndex = 3,
	}
	D.LEEROYLINK_LAYERHOP.button1 = T("Einladen", "Invite")
	D.LEEROYLINK_LAYERHOP.button2 = T("Ablehnen", "Decline")
	return try(G("StaticPopup_Show"), "LEEROYLINK_LAYERHOP",
		string.format(T("Leeroylink: %s möchte auf deinen Layer wechseln.\nEinladen? (Die Gruppe wird gleich wieder verlassen.)",
			"Leeroylink: %s wants to switch to your layer.\nInvite? (They leave the group again right away.)"), name))
end

function mod:HandleRequest(from, charName)
	local who = base(charName) or base(from.name) or "?"
	local function no(reason) send(from, "NO", reason) end
	if not self.opt.host then return no("off") end
	if not allowed(from) then return no("stranger") end
	if inInstance() then return no("instance") end
	if inCombat() then return no("combat") end
	if groupHas(from.name or who) then return no("same") end
	if not canInvite() then return no("lead") end
	if inGroup() and groupSize() >= (inRaid() and 40 or 5) then return no("full") end
	local p = host.pending
	if p and p.key == lkey(who) and time() - p.at < 5 then return end      -- the same request twice
	if p and p.key ~= lkey(who) and time() - p.at < HOST_TIMEOUT + 5 then return no("busy") end
	host.pending = { from = from, name = who, key = lkey(who), at = time() }
	if self.opt.autoInvite then return self:Invite() end
	send(from, "ACK", zoneMap() or 0)
	if not askHost(who) then
		self:Print(string.format(T("%s möchte auf deinen Layer wechseln: /lz layer ja oder /lz layer nein", "%s wants to switch to your layer: /lz layer yes or /lz layer no"), who))
	end
	local at = host.pending.at
	LZ.After(HOST_TIMEOUT + 2, function()
		if host.pending and host.pending.at == at then mod:Decline(true) end
	end)
end

----------------------------------------------------------------------
-- Incoming messages
----------------------------------------------------------------------
local REASONS = {
	off = { "%s nimmt keine Layer-Anfragen an.", "%s does not take layer requests." },
	stranger = { "%s nimmt nur Anfragen von Freunden und Gilde an.", "%s only takes requests from friends and guild." },
	combat = { "%s ist gerade im Kampf – gleich nochmal versuchen.", "%s is in combat – try again in a moment." },
	instance = { "%s ist in einer Instanz.", "%s is in an instance." },
	same = { "Ihr seid schon in einer Gruppe.", "You are already in a group together." },
	lead = { "%s ist in einer Gruppe, führt sie aber nicht – kann dich nicht einladen.", "%s is in a group but does not lead it – cannot invite you." },
	full = { "Die Gruppe von %s ist voll.", "%s's group is full." },
	busy = { "%s beantwortet gerade eine andere Anfrage – gleich nochmal.", "%s is answering another request – try again shortly." },
	declined = { "%s hat abgelehnt (oder nicht reagiert).", "%s declined (or did not react)." },
	invite = { "%s konnte dich nicht einladen.", "%s could not invite you." },
}

local function isTarget(from)
	local t = rq.target
	if not t then return false end
	if from.bnet and t.bnet and from.bnet == t.bnet then return true end
	return lkey(from.name) == t.key
end

function mod:OnMessage(text, from)
	if type(text) ~= "string" then return end
	local parts = {}
	for p in (text .. SEP):gmatch("(.-)" .. SEP) do parts[#parts + 1] = p end
	if parts[1] ~= VER then return end
	local k = lkey(from.name)
	if k and k == lkey(myName()) then return end   -- my own guild message
	local cmd = parts[2]
	if k then
		seen[k] = seen[k] or {}
		seen[k].t = time()
	end
	if cmd == "PING" then
		if allowed(from) then send(from, "PONG", LZ.version, self.opt.host and 1 or 0, zoneMap() or 0) end
	elseif cmd == "PONG" then
		if k then seen[k] = { v = parts[3], h = parts[4] == "1", map = tonumber(parts[5]), t = time() } end
		if refreshWindow then refreshWindow() end
	elseif cmd == "REQ" then
		self:HandleRequest(from, parts[4])
	elseif (cmd == "ACK" or cmd == "INV") and isTarget(from) and rq.state == "joined" then
		-- the invite came before this message: plan again if the other one is in another zone
		local m = tonumber(parts[3])
		if m and m > 0 and m ~= rq.hostMap then
			rq.hostMap = m
			if m ~= zoneMap() then self:PlanLeave() end
		end
	elseif (cmd == "ACK" or cmd == "INV") and isTarget(from) and (rq.state == "asking" or rq.state == "waiting") then
		local m = tonumber(parts[3])
		rq.hostMap = (m and m > 0) and m or rq.hostMap
		if rq.state == "asking" then
			toWaiting()
			if cmd == "ACK" then
				self:Print(string.format(T("%s wird gefragt …", "%s is being asked …"), targetName()))
			end
		end
	elseif cmd == "NO" and isTarget(from) and (rq.state == "asking" or rq.state == "waiting") then
		local r = REASONS[parts[3] or ""]
		self:Print(r and string.format(P(r), targetName())
			or string.format(T("%s: Wechsel nicht möglich (%s).", "%s: switch not possible (%s)."), targetName(), tostring(parts[3])))
		resetRq()
	end
end

mod:Event("CHAT_MSG_ADDON", function(self, _, prefix, text, channel, sender)
	if prefix ~= PREFIX then return end
	self:OnMessage(text, { name = sender, channel = channel })
end)

mod:Event("BN_CHAT_MSG_ADDON", function(self, _, prefix, text, _, senderID)
	if prefix ~= PREFIX then return end
	local ga = call(NS("C_BattleNet", "GetGameAccountInfoByID"), senderID)
	local name = type(ga) == "table" and ga.characterName or nil
	self:OnMessage(text, { bnet = senderID, name = name })
end)

local function rosterChanged()
	scannedAt = -100
	if refreshWindow then refreshWindow(true) end
end
mod:Event("FRIENDLIST_UPDATE", rosterChanged)
mod:Event("GUILD_ROSTER_UPDATE", rosterChanged)
mod:Event("BN_FRIEND_INFO_CHANGED", rosterChanged)

function mod:OnEnable()
	local CI = _G.C_ChatInfo
	if not (type(CI) == "table" and try(CI.RegisterAddonMessagePrefix, PREFIX)) then
		try(G("RegisterAddonMessagePrefix"), PREFIX)
	end
end

function mod:OnDisable()
	if rq.state ~= "joined" then resetRq() end
	if host.pending then self:Decline(true) end
	if self.window then self.window:Hide() end
end

----------------------------------------------------------------------
-- What the window and the pages show
----------------------------------------------------------------------
function mod:State() return rq.state, rq.target, rq end

local function statusText()
	local name = targetName()
	if rq.state == "asking" then return string.format(T("Frage %s nach einer Einladung …", "Asking %s for an invite …"), name) end
	if rq.state == "waiting" then return string.format(T("Warte auf die Einladung von %s …", "Waiting for %s's invite …"), name) end
	if rq.state == "joined" then
		if rq.target and rq.target.keep then return string.format(T("In der Gruppe von %s (bleibt).", "In %s's group (staying)."), name) end
		if rq.waitZone then return string.format(T("In der Gruppe von %s – wechselt, sobald du dort bist (%s).", "In %s's group – switches once you are there (%s)."), name, mapName(rq.waitZone)) end
		if rq.leaveAt then
			return string.format(T("In der Gruppe von %s – verlässt sie in %d s.", "In %s's group – leaving in %d s."), name, math.max(0, rq.leaveAt - time()))
		end
		return string.format(T("In der Gruppe von %s.", "In %s's group."), name)
	end
	return nil
end

local function viaText(c)
	local out = {}
	for _, v in ipairs(c.via or {}) do out[#out + 1] = P(VIA[v] or { v, v }) end
	return table.concat(out, ", ")
end

local function lzText(c)
	local s = seen[c.key]
	if not s then return LZ.Color("808080", T("Leeroylink ?", "Leeroylink ?")) end
	if s.v and s.h == false then return LZ.Color("a06000", T("nimmt keine Anfragen an", "takes no requests")) end
	return LZ.Color("208020", "Leeroylink" .. (s.v and (" " .. s.v) or ""))
end

local function classColored(name, class)
	local c = _G.RAID_CLASS_COLORS and class and RAID_CLASS_COLORS[class]
	if type(c) == "table" and c.colorStr then return "|c" .. c.colorStr .. name .. "|r" end
	return name
end

function mod:Lines(c)
	local zone = c.zone and c.zone ~= "" and c.zone or "?"
	if c.here then zone = zone .. " " .. LZ.Color("208020", T("(hier)", "(here)")) end
	local info = zone .. "  ·  " .. viaText(c) .. "  ·  " .. lzText(c)
	if c.inGroup then info = info .. "  ·  " .. T("in deiner Gruppe", "in your group") end
	local who = classColored(c.name, c.class) .. (c.level and c.level ~= 0 and LZ.Color("808080", " " .. tostring(c.level)) or "")
	if c.account then who = who .. LZ.Color("808080", " (" .. c.account .. ")") end
	return who, info
end

function mod:Summary()
	local st = statusText()
	if st then return st end
	local n, withLZ = 0, 0
	for _, c in ipairs(self:Scan()) do
		n = n + 1
		if seen[c.key] then withLZ = withLZ + 1 end
	end
	return string.format(T("%d Freunde/Gilde online, %d mit Leeroylink", "%d friends/guild online, %d with Leeroylink"), n, withLZ)
end

function mod:TooltipLines()
	local st = statusText()
	if st then return { T("Layerwechsel: ", "Layer switch: ") .. st } end
end

function mod:Report()
	self:Ping()
	local list = self:Scan(true)
	local lines = {}
	local st = statusText()
	if st then lines[#lines + 1] = LZ.Color("ffd100", st); lines[#lines + 1] = "" end
	lines[#lines + 1] = LZ.Color("ffd100", T("Online", "Online"))
	if #list == 0 then lines[#lines + 1] = T("Keine Freunde oder Gildenmitglieder online.", "No friends or guild mates online.") end
	for i = 1, math.min(#list, 25) do
		local who, info = self:Lines(list[i])
		lines[#lines + 1] = who .. "  –  " .. info
	end
	if #list > 25 then lines[#lines + 1] = string.format(T("… und %d weitere", "… and %d more"), #list - 25) end
	lines[#lines + 1] = ""
	lines[#lines + 1] = LZ.Color("ffd100", T("So geht's", "How it works"))
	lines[#lines + 1] = T("Fenster öffnen und bei einem Spieler auf Wechseln klicken – oder /lz layer <Name>. Das Leeroylink des anderen lädt dich ein, du nimmst an, nach ein paar Sekunden verlässt du die Gruppe wieder und bleibst auf diesem Layer. Beide brauchen Leeroylink 0.11 oder neuer – sonst kann der andere dich auch von Hand einladen.",
		"Open the window and click Switch next to a player – or /lz layer <name>. Their Leeroylink invites you, you accept, a few seconds later you leave the group again and stay on their layer. Both need Leeroylink 0.11 or newer; without it they can simply invite you by hand.")
	lines[#lines + 1] = T("Ist der andere in einer anderen Zone, wechselt der Layer erst, wenn du dort ankommst. Blizzard lässt Wechsel nicht beliebig oft zu – klappt es nicht, ein paar Minuten warten.",
		"If they are in another zone, the layer changes once you arrive there. Blizzard does not allow switches without limit – if it does not work, wait a few minutes.")
	lines[#lines + 1] = LZ.Color("808080", T("Einen bestimmten Layer (1, 2, 3 …) wählen geht in WoW Forever seit dem 20.11.2026 nicht mehr: Blizzard verbirgt den Layer vor Addons.",
		"Picking a numbered layer (1, 2, 3 …) is not possible in WoW Forever since Nov 20, 2026: Blizzard hides the layer from addons."))
	lines[#lines + 1] = LZ.Color("808080", "/lz layer  ·  /lz layer <Name>  ·  /lz layer verlassen  ·  /lz layer stop  ·  /lz layer warten <Sek.>")
	return table.concat(lines, "\n")
end

mod.actions = {
	{ label = { "Fenster öffnen", "Open window" }, fn = function(m) m:ShowWindow() end },
	{ label = { "Aktualisieren", "Refresh" }, fn = function(m) m:Ping(true); m:Scan(true) end },
}

----------------------------------------------------------------------
-- Window: everyone online, one click to switch
----------------------------------------------------------------------
local WIDTH, HEIGHT, ROW_H = 420, 460, 34
local win

local function row(i)
	local r = win.rows[i]
	if r then return r end
	local Skin = LZ.Skin
	r = CreateFrame("Frame", nil, win.content)
	r:SetSize(WIDTH - 70, ROW_H)
	r:SetPoint("TOPLEFT", 0, -(i - 1) * ROW_H)
	r.go = Skin.Button(r, T("Wechseln", "Switch"), 86, function()
		if r.cand then LZ:Safe(mod.Hop, mod, r.cand) end
	end)
	r.go:SetPoint("RIGHT", -2, 0)
	r.name = Skin.Text(r)
	r.name:SetPoint("TOPLEFT", 4, -3)
	r.name:SetPoint("RIGHT", r.go, "LEFT", -6, 0)
	r.info = Skin.Text(r, "small")
	r.info:SetPoint("TOPLEFT", r.name, "BOTTOMLEFT", 0, -2)
	r.info:SetPoint("RIGHT", r.go, "LEFT", -6, 0)
	for _, fs in ipairs({ r.name, r.info }) do
		if fs.SetWordWrap then fs:SetWordWrap(false) end      -- one line each, cut with "…"
	end
	win.rows[i] = r
	return r
end

local function fill()
	if not (win and win:IsShown()) then return end
	local Skin = LZ.Skin
	local list = mod:Scan()
	local st = statusText()
	local busy = rq.state ~= "idle"
	win.status:SetText(Skin.OnParchment(st and LZ.Color("ffd100", st) or T("Zu wem möchtest du wechseln? Du landest auf demselben Layer.", "Who do you want to switch to? You end up on the same layer.")))
	win.hint:SetText(Skin.OnParchment(LZ.Color("808080", #list == 0 and T("Keine Freunde oder Gildenmitglieder online.", "No friends or guild mates online.")
		or T("Beide brauchen Leeroylink 0.11+. Einen bestimmten Layer wählen lässt Blizzard nicht mehr zu.", "Both need Leeroylink 0.11+. Blizzard no longer allows picking a numbered layer."))))
	for i, c in ipairs(list) do
		local r = row(i)
		local who, info = mod:Lines(c)
		r.cand = c
		r.name:SetText(Skin.OnParchment(who))
		r.info:SetText(Skin.OnParchment(info))
		local s = seen[c.key]
		if busy or c.inGroup or (s and s.v and s.h == false) then r.go:Disable() else r.go:Enable() end
		r:Show()
	end
	for i = #list + 1, #win.rows do win.rows[i]:Hide(); win.rows[i].cand = nil end
	win.content:SetHeight(math.max(10, #list * ROW_H))
	if rq.state == "joined" then win.leave:Enable() else win.leave:Disable() end
	if busy then win.cancel:Enable() else win.cancel:Disable() end
end

local pendingFill = false
refreshWindow = function(rescan)
	if not (win and win:IsShown()) then return end
	if rescan then scannedAt = -100 end
	if pendingFill then return end
	pendingFill = true
	LZ.After(0.3, function() pendingFill = false; LZ:Safe(fill) end)
end

local function build()
	if win then return end
	local Skin = LZ.Skin
	win = Skin.Window("LeeroylinkLayerHop", P(mod.title), WIDTH, HEIGHT, {
		pos = mod.opt.pos, save = function(p) mod.opt.pos = p end, anchor = "CENTER", x = 280, y = 40,
	})
	mod.window = win
	local portrait = Skin.Portrait(win)
	if portrait then
		portrait:SetTexture("Interface\\Icons\\Spell_Arcane_PortalStormwind")
		if not portrait:GetTexture() then portrait:SetTexture(Skin.ICON) end
	end
	local page = CreateFrame("Frame", nil, win.body)
	page:SetAllPoints()
	Skin.Parchment(page)
	win.status = Skin.Text(page)
	win.status:SetPoint("TOPLEFT", 16, -12)
	win.status:SetPoint("RIGHT", -16, 0)
	win.hint = Skin.Text(page, "small")
	win.hint:SetPoint("TOPLEFT", win.status, "BOTTOMLEFT", 0, -6)
	win.hint:SetPoint("RIGHT", -16, 0)
	win.scroll, win.content = Skin.Scroll(page, 12, -80, -6, 8)
	win.content:SetSize(WIDTH - 70, 10)
	win.rows = {}

	win.refresh = Skin.Button(win, T("Aktualisieren", "Refresh"), 110, function()
		mod:Ping(true)
		scannedAt = -100
		LZ:Safe(fill)
	end)
	win.refresh:SetPoint("BOTTOMRIGHT", win, "BOTTOMRIGHT", -8, 4)
	win.leave = Skin.Button(win, T("Gruppe verlassen", "Leave group"), 130, function() LZ:Safe(mod.Leave, mod) end)
	win.leave:SetPoint("RIGHT", win.refresh, "LEFT", -4, 0)
	win.cancel = Skin.Button(win, T("Abbrechen", "Cancel"), 100, function() LZ:Safe(mod.Cancel, mod) end)
	win.cancel:SetPoint("RIGHT", win.leave, "LEFT", -4, 0)

	-- the countdown in the status line
	local acc = 0
	win:SetScript("OnUpdate", function(_, dt)
		acc = acc + (dt or 0)
		if acc >= 1 then
			acc = 0
			if rq.state == "joined" and rq.leaveAt then LZ:Safe(fill) end
		end
	end)
	win:HookScript("OnShow", function()
		local GI = _G.C_GuildInfo
		if not (type(GI) == "table" and try(GI.GuildRoster)) then try(G("GuildRoster")) end
		try(NS("C_FriendList", "ShowFriends"))
		mod:Ping()
		scannedAt = -100
		LZ:Safe(fill)
	end)
end

function mod:ShowWindow()
	build()
	win:Show()
	LZ:Safe(fill)
end

function mod:ToggleWindow()
	build()
	if win:IsShown() then win:Hide() else self:ShowWindow() end
end

----------------------------------------------------------------------
-- /lz layer
----------------------------------------------------------------------
local SUB = {
	verlassen = "leave", leave = "leave", raus = "leave",
	stop = "stop", abbrechen = "stop", cancel = "stop",
	ja = "yes", yes = "yes", einladen = "yes", invite = "yes",
	nein = "no", no = "no", ablehnen = "no", decline = "no",
	warten = "wait", wait = "wait",
	liste = "list", list = "list",
}

mod:Command({ "layer", "layerwechsel", "hop" }, function(self, rest)
	local sub, arg = rest:match("^(%S*)%s*(.-)$")
	local cmd = SUB[(sub or ""):lower()]
	if rest == "" then self:ToggleWindow() return end
	if cmd == "leave" then self:Leave()
	elseif cmd == "stop" then if not self:Cancel() then self:Print(T("Es läuft gerade kein Wechsel.", "No switch is running.")) end
	elseif cmd == "yes" then if not self:Invite() then self:Print(T("Keine offene Anfrage.", "No open request.")) end
	elseif cmd == "no" then if not self:Decline() then self:Print(T("Keine offene Anfrage.", "No open request.")) end
	elseif cmd == "wait" then
		local n = tonumber(arg)
		if n then self.opt.leaveDelay = math.max(2, math.min(60, math.floor(n))) end
		self:Print(string.format(T("Gruppe verlassen nach %d s.", "Leave the group after %d s."), delay()))
	elseif cmd == "list" then
		local list = self:Scan(true)
		if #list == 0 then self:Print(T("Keine Freunde oder Gildenmitglieder online.", "No friends or guild mates online.")) end
		for i = 1, math.min(#list, 20) do
			local who, info = self:Lines(list[i])
			self:Print(who .. "  –  " .. info)
		end
	else
		local c = self:Find(rest)
		if c then self:Hop(c)
		else self:Print(string.format(T("„%s“ ist nicht unter deinen Freunden oder in der Gilde online.", "\"%s\" is not online among your friends or guild."), rest)) end
	end
end, { "layer [<Name>|verlassen|stop|warten <Sek.>]", "auf den Layer eines Freundes wechseln", "switch to a friend's layer" })
