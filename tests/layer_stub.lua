-- layer_stub.lua: what the layer switch needs on top of wow_stub.lua – player name, friends,
-- Battle.net friends, guild, group, addon messages and popups. Messages and invites only land in
-- STUB tables; tests/test_layerhop.py carries them between two clients.
STUB.me = "Rosenbert"
STUB.realm = "CAMWOWEU5Realm2PvP"
STUB.party = {}              -- names of party1..party4
STUB.partyMaps = {}          -- [unit] = map ID
STUB.leader = false
STUB.outbox, STUB.prefixes = {}, {}
STUB.friends, STUB.bnFriends, STUB.guild = {}, {}, {}
STUB.inGuild = false
STUB.invited, STUB.popups, STUB.hidden = {}, {}, {}
STUB.accepted, STUB.left = 0, 0

local origUnitName = UnitName
function UnitName(u)
	if u == "player" then return STUB.me end
	local i = type(u) == "string" and tonumber(u:match("^party(%d)$"))
	if i then return STUB.party[i] end
	return origUnitName(u)
end
function GetRealmName() return STUB.realm end
function GetNormalizedRealmName() return STUB.realm end

function InCombatLockdown() return STUB.combat end
function IsInGroup() return STUB.group > 0 end
function IsInRaid() return false end
function UnitIsGroupLeader() return STUB.leader end
function GetNumGroupMembers() return STUB.group end

local origBest = C_Map.GetBestMapForUnit
function C_Map.GetBestMapForUnit(u)
	if STUB.partyMaps[u] then return STUB.partyMaps[u] end
	return origBest(u)
end

C_ChatInfo = {
	RegisterAddonMessagePrefix = function(p) STUB.prefixes[p] = true; return true end,
	SendAddonMessage = function(prefix, msg, chatType, target)
		table.insert(STUB.outbox, { prefix = prefix, msg = msg, chatType = chatType, target = target })
		return 0
	end,
}
function BNSendGameData(id, prefix, msg)
	table.insert(STUB.outbox, { prefix = prefix, msg = msg, chatType = "BN", bnet = id })
end

-- Battle.net friends: { account = "Name#1234", id = gameAccountID, char = "Name", area = "Zone", faction = "Alliance" }
function BNGetNumFriends() return #STUB.bnFriends, #STUB.bnFriends end
local function gameInfo(f)
	return { gameAccountID = f.id, isOnline = true, clientProgram = "WoW", characterName = f.char, areaName = f.area,
		factionName = f.faction or "Alliance", characterLevel = 30, className = "Mage" }
end
C_BattleNet = {
	GetFriendAccountInfo = function(i)
		local f = STUB.bnFriends[i]
		if f then return { accountName = f.account, battleTag = f.account, gameAccountInfo = gameInfo(f) } end
	end,
	GetFriendNumGameAccounts = function(i) return STUB.bnFriends[i] and 1 or 0 end,
	GetFriendGameAccountInfo = function(i) local f = STUB.bnFriends[i]; return f and gameInfo(f) end,
	GetGameAccountInfoByID = function(id)
		for _, f in ipairs(STUB.bnFriends) do if f.id == id then return gameInfo(f) end end
	end,
}

-- friends: { name = "Name", area = "Zone", connected = true }
C_FriendList = {
	GetNumFriends = function() return #STUB.friends end,
	GetFriendInfoByIndex = function(i)
		local f = STUB.friends[i]
		if f then return { name = f.name, area = f.area, connected = f.connected ~= false, level = 25, className = "Warrior" } end
	end,
	ShowFriends = function() end,
}

-- guild: { name = "Name-Realm", zone = "Zone", online = true }
function IsInGuild() return STUB.inGuild end
function GetNumGuildMembers() return #STUB.guild, #STUB.guild end
function GetGuildRosterInfo(i)
	local m = STUB.guild[i]
	if m then return m.name, "Mitglied", 3, 20, "Priester", m.zone, "", "", m.online ~= false, 0, "PRIEST" end
end
C_GuildInfo = { GuildRoster = function() end }

C_PartyInfo = {
	InviteUnit = function(name) table.insert(STUB.invited, name) end,
	LeaveParty = function() STUB.left = STUB.left + 1 end,
}
function AcceptGroup() STUB.accepted = STUB.accepted + 1 end

StaticPopupDialogs = {}
function StaticPopup_Show(which, text)
	table.insert(STUB.popups, { which = which, text = text })
	return {}
end
function StaticPopup_Hide(which) STUB.hidden[which] = (STUB.hidden[which] or 0) + 1 end
