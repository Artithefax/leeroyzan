-- UI.lua: the main window in the game's own look (portrait frame, tabs at the bottom, parchment pages),
-- the settings page and the minimap button. Building blocks: Core/Skin.lua.
local ADDON, LZ = ...
local T, P = LZ.T, LZ.P
local Skin = LZ.Skin

local UI = {}
LZ.UI = UI

local W, H, LIST_W = 760, 540, 170

-- Tabs and the modules on them. Modules not listed here land on "Addons".
local TABS = {
	{ key = "overview", label = { "Übersicht", "Overview" } },
	{ key = "session", label = { "Sitzung", "Session" }, mods = { "Session", "Map", "LootLog", "Screenshots" } },
	{ key = "quests", label = { "Quests", "Quests" }, mods = { "QuestGuide", "Tasks", "Notes" } },
	{ key = "chars", label = { "Charaktere", "Characters" }, mods = { "Alts", "Recipes", "Prices", "LayerHop" } },
	{ key = "addons", label = { "Addons", "Addons" }, mods = { "Updates", "ErrorLog", "LoadStatus", "Profiles", "Wishlist", "Memory" } },
	{ key = "settings", label = { "Einstellungen", "Settings" }, mods = { "LeeroyMode", "Automation" } },
}
local tabOf = {}
for i, tab in ipairs(TABS) do
	for _, m in ipairs(tab.mods or {}) do tabOf[m] = i end
end

-- pages of a tab: { key, label, mod }
local function tabPages(i)
	local tab, out = TABS[i], {}
	if tab.key == "settings" then out[1] = { key = "settings", label = T("Allgemein", "General") } end
	for _, mod in ipairs(LZ.moduleList) do
		if mod.Report and (tabOf[mod.name] or 5) == i then
			out[#out + 1] = { key = mod.name, label = P(mod.title), mod = mod, off = not mod.enabled }
		end
	end
	return out
end

----------------------------------------------------------------------
-- Settings page (on parchment)
----------------------------------------------------------------------
local settingsRows = {}

local function buildSettings(parent)
	local page = CreateFrame("Frame", nil, parent)
	page:SetAllPoints()
	Skin.Parchment(page)
	local scroll, f = Skin.Scroll(page, 18, -14, -8, 12)
	f:SetSize(420, 600)
	local y = -2

	local function header(textFn)
		local fs = Skin.Text(f, "title")
		fs:SetPoint("TOPLEFT", 0, y)
		settingsRows[#settingsRows + 1] = { update = function() fs:SetText(textFn()) end }
		y = y - 26
	end

	local function checkbox(x, labelFn, getFn, setFn)
		local cb = CreateFrame("CheckButton", nil, f, "UICheckButtonTemplate")
		cb:SetPoint("TOPLEFT", x, y + 4)
		cb:SetSize(24, 24)
		local fs = Skin.Text(f)
		fs:SetPoint("LEFT", cb, "RIGHT", 4, 0)
		fs:SetWidth(380 - x)
		cb:SetScript("OnClick", function(self)
			Skin.Sound(self:GetChecked() and "IG_MAINMENU_OPTION_CHECKBOX_ON" or "IG_MAINMENU_OPTION_CHECKBOX_OFF")
			setFn(self:GetChecked() and true or false)
			if UI.frame then UI:Refresh() end
		end)
		settingsRows[#settingsRows + 1] = { update = function() fs:SetText(labelFn()); cb:SetChecked(getFn()) end }
		y = y - 26
	end

	header(function() return T("Sprache", "Language") end)
	local de = Skin.Button(f, "Deutsch", 90, function() LZ.coreCommands["sprache"]("de") end)
	de:SetPoint("TOPLEFT", 0, y + 2)
	local en = Skin.Button(f, "English", 90, function() LZ.coreCommands["sprache"]("en") end)
	en:SetPoint("LEFT", de, "RIGHT", 6, 0)
	y = y - 34

	header(function() return T("Darstellung", "Display") end)
	checkbox(0, function() return T("Minimap-Symbol anzeigen", "Show minimap button") end,
		function() return not LZ.settings.minimap.hide end,
		function(v) LZ.settings.minimap.hide = not v; UI:UpdateMinimap() end)
	checkbox(0, function() return T("Einblendungen oben im Bild (Updates, Fehler, Questreihen, Bosse)", "Banners at the top of the screen (updates, errors, quest chains, bosses)") end,
		function() return Skin.UISettings().banners end,
		function(v) Skin.UISettings().banners = v end)
	checkbox(0, function() return T("Klänge beim Öffnen und für Einblendungen", "Sounds when opening and for banners") end,
		function() return Skin.UISettings().sound end,
		function(v) Skin.UISettings().sound = v end)
	local test = Skin.Button(f, T("Einblendung testen", "Test banner"), 160, function() LZ.coreCommands["banner"]() end)
	test:SetPoint("TOPLEFT", 28, y + 2)
	settingsRows[#settingsRows + 1] = { update = function() test:SetText(T("Einblendung testen", "Test banner")) end }
	y = y - 34

	local groups = {
		{ "link", function() return T("Verbindung zu Leeroyzan", "Leeroyzan link") end },
		{ "extra", function() return T("Zusatzfunktionen", "Extras") end },
	}
	for _, g in ipairs(groups) do
		header(g[2])
		for _, mod in ipairs(LZ.moduleList) do
			if mod.group == g[1] then
				checkbox(0, function() return P(mod.title) end,
					function() return mod.enabled end,
					function(v) LZ:SetModuleEnabled(mod, v) end)
				for _, o in ipairs(mod.options or {}) do
					checkbox(26, function() return Skin.OnParchment(LZ.Color("808080", P(o.label))) end,
						function() return mod.opt[o.key] and true or false end,
						function(v) mod.opt[o.key] = v end)
				end
			end
		end
		y = y - 8
	end
	f:SetHeight(-y + 10)
	page.scroll, page.content = scroll, f
	return page
end

----------------------------------------------------------------------
-- Overview: what Leeroylink knows right now, grouped like the tabs
----------------------------------------------------------------------
local function overviewText()
	local lines = {}
	if not LZ.import then
		lines[#lines + 1] = LZ.Color("808080", T("Noch keine Daten von Leeroyzan – Manager starten, dann /reload.", "No data from Leeroyzan yet – start the manager, then /reload."))
	end
	for i, tab in ipairs(TABS) do
		if tab.mods then
			local rows = {}
			for _, mod in ipairs(LZ.moduleList) do
				if (tabOf[mod.name] or 5) == i and (mod.Report or mod.Summary) then
					local summary
					if mod.enabled and mod.Summary then
						local ok, s = pcall(mod.Summary, mod)
						summary = ok and tostring(s) or "?"
					elseif not mod.enabled then
						summary = LZ.Color("808080", T("aus", "off"))
					end
					if summary and summary ~= "" then rows[#rows + 1] = LZ.Color("4a2a08", P(mod.title)) .. ":  " .. summary end
				end
			end
			if #rows > 0 then
				lines[#lines + 1] = ""
				lines[#lines + 1] = LZ.Color(Skin.TITLE_HEX, P(tab.label))
				for _, r in ipairs(rows) do lines[#lines + 1] = "  " .. r end
			end
		end
	end
	lines[#lines + 1] = ""
	lines[#lines + 1] = LZ.Color("808080", T("Befehle: /lz hilfe · Minimap-Symbol: Linksklick Fenster, Rechtsklick Einstellungen",
		"Commands: /lz help · Minimap button: left click window, right click settings"))
	return table.concat(lines, "\n")
end

----------------------------------------------------------------------
-- Main window
----------------------------------------------------------------------
function UI:Build()
	if self.frame then return end
	local s = Skin.UISettings()
	local f = Skin.Window("LeeroylinkFrame", "Leeroylink", W, H, {
		pos = s.pos, save = function(p) s.pos = p end, strata = "HIGH",
	})
	self.frame = f
	local body = f.body

	-- left list (pages of the tab) and the page area
	self.list = Skin.List(body, LIST_W, function(key) UI:Select(key) end)
	local area = CreateFrame("Frame", nil, body)
	area:SetPoint("TOPLEFT", LIST_W + 6, -4)
	area:SetPoint("BOTTOMRIGHT", -4, 4)
	self.area = area
	self.page = Skin.ParchmentPage(area)
	self.page.defaultWidth = W - LIST_W - 60
	self.settings = buildSettings(area)
	self.settings:Hide()

	-- action buttons in the button bar at the bottom
	self.actions = {}
	for i = 1, 3 do
		local b = Skin.Button(f, "", 150, function() end)
		b:SetPoint("BOTTOMRIGHT", f, "BOTTOMRIGHT", -8 - (i - 1) * 154, 4)
		b:Hide()
		self.actions[i] = b
	end

	-- status line in the strip under the title, next to the portrait
	local status = f:CreateFontString(nil, "OVERLAY", "GameFontHighlightSmall")
	status:SetPoint("TOPLEFT", f, "TOPLEFT", 64, -34)
	status:SetPoint("RIGHT", f, "RIGHT", -12, 0)
	status:SetJustifyH("LEFT")
	self.status = status

	local labels = {}
	for i, tab in ipairs(TABS) do labels[i] = P(tab.label) end
	self.tabButtons = Skin.Tabs(f, labels, function(i) UI:SelectTab(i) end)

	f:HookScript("OnShow", function() UI:Refresh() end)
	self.tab = self.tab or 1
end

function UI:Rebuild()
	if not self.frame then return end
	for i, tab in ipairs(self.tabButtons or {}) do
		tab:SetText(P(TABS[i].label))
		if _G.PanelTemplates_TabResize then pcall(PanelTemplates_TabResize, tab, 0) end
	end
	if self.frame.SetTitle then self.frame:SetTitle("Leeroylink") end
	self:Refresh()
end

function UI:SelectTab(i)
	self.tab = i
	self.key = nil
	self:Refresh()
end

function UI:Select(key)
	self.key = key
	self:Refresh()
end

local function findTab(key)
	if key == "overview" then return 1 end
	if key == "settings" then return #TABS end
	local mod = LZ.modules[key]
	if mod then return tabOf[mod.name] or 5 end
	return nil
end

function UI:Refresh()
	local f = self.frame
	if not f then return end
	self.tab = self.tab or 1
	f:SelectTab(self.tab)
	local pages = tabPages(self.tab)
	local tab = TABS[self.tab]

	-- overview: no list, the page uses the whole width
	if tab.key == "overview" then
		self.list:Hide()
		self.area:SetPoint("TOPLEFT", 4, -4)
		self.key = "overview"
	else
		self.list:Show()
		self.area:SetPoint("TOPLEFT", LIST_W + 6, -4)
		local valid = false
		for _, p in ipairs(pages) do if p.key == self.key then valid = true end end
		if not valid then self.key = pages[1] and pages[1].key end
		self.list:SetItems(pages, self.key)
	end

	local imp = LZ.import
	self.status:SetText(imp and string.format(T("Daten von Leeroyzan: %s  ·  %d Updates", "Data from Leeroyzan: %s  ·  %d updates"), LZ.Ago(imp.generated), #imp.updates)
		or LZ.Color("a0a0a0", T("Noch keine Daten von Leeroyzan", "No data from Leeroyzan yet")))

	local acts
	if self.key == "settings" then
		self.page:Hide()
		self.settings:Show()
		for _, row in ipairs(settingsRows) do row.update() end
	else
		self.settings:Hide()
		self.page:Show()
		local mod = LZ.modules[self.key or ""]
		if self.key == "overview" then
			self.page:SetPage("Leeroylink  " .. LZ.Color("808080", "v" .. LZ.version), nil, overviewText())
		elseif not mod then
			self.page:SetPage(P(tab.label), nil, "")
		elseif not mod.enabled then
			self.page:SetPage(P(mod.title), mod.desc and P(mod.desc),
				LZ.Color("a02020", T("Dieses Modul ist ausgeschaltet. Einschalten unter Einstellungen.", "This module is off. Switch it on under Settings.")))
		else
			local ok, result = pcall(mod.Report, mod)
			self.page:SetPage(P(mod.title), mod.desc and P(mod.desc), ok and tostring(result) or ("|cffff4040Error:|r " .. tostring(result)))
			acts = mod.actions
		end
	end

	for i, b in ipairs(self.actions) do
		local a = acts and acts[i]
		if a then
			b:SetText(P(a.label))
			local key = self.key
			b:SetScript("OnClick", function() a.fn(LZ.modules[key]); UI:Refresh() end)
			b:Show()
		else
			b:Hide()
		end
	end
end

function UI:Show(key)
	self:Build()
	if key then
		self.tab = findTab(key) or self.tab
		self.key = key
	end
	self.frame:Show()
	self:Refresh()
end

function UI:Toggle()
	self:Build()
	if self.frame:IsShown() then self.frame:Hide() else self:Show() end
end

----------------------------------------------------------------------
-- Minimap button: own icon in the round tracking border
----------------------------------------------------------------------
local button

local function placeButton()
	if not button then return end
	local angle = LZ.settings.minimap.angle or 3.9
	local r = (Minimap:GetWidth() / 2) + 5
	button:ClearAllPoints()
	button:SetPoint("CENTER", Minimap, "CENTER", math.cos(angle) * r, math.sin(angle) * r)
end

function UI:BuildMinimap()
	if button or not _G.Minimap then return end
	button = CreateFrame("Button", "LeeroylinkMinimapButton", Minimap)
	button:SetSize(31, 31)
	button:SetFrameStrata("MEDIUM")
	button:SetFrameLevel(8)
	button:RegisterForClicks("LeftButtonUp", "RightButtonUp")
	button:RegisterForDrag("LeftButton")
	button:SetHighlightTexture("Interface\\Minimap\\UI-Minimap-ZoomButton-Highlight")

	local back = button:CreateTexture(nil, "BACKGROUND")
	back:SetSize(24, 24)
	back:SetTexture("Interface\\Minimap\\UI-Minimap-Background")
	back:SetPoint("CENTER", 0, 1)
	local icon = button:CreateTexture(nil, "ARTWORK")
	icon:SetSize(22, 22)
	icon:SetPoint("CENTER", 0, 1)
	icon:SetTexture(Skin.ICON)
	if not icon:GetTexture() then icon:SetTexture(Skin.ICON_FALLBACK) end
	if icon.SetTexCoord then icon:SetTexCoord(0.06, 0.94, 0.06, 0.94) end
	local border = button:CreateTexture(nil, "OVERLAY")
	border:SetSize(53, 53)
	border:SetTexture("Interface\\Minimap\\MiniMap-TrackingBorder")
	border:SetPoint("TOPLEFT")
	button.icon = icon

	button:SetScript("OnMouseDown", function() icon:SetPoint("CENTER", 1, 0) end)
	button:SetScript("OnMouseUp", function() icon:SetPoint("CENTER", 0, 1) end)
	button:SetScript("OnClick", function(_, btn)
		if btn == "RightButton" then
			UI:Show("settings")
		elseif IsShiftKeyDown and IsShiftKeyDown() then
			ReloadUI()
		else
			UI:Toggle()
		end
	end)

	button:SetScript("OnDragStart", function(self)
		self:SetScript("OnUpdate", function()
			local mx, my = Minimap:GetCenter()
			local px, py = GetCursorPosition()
			local scale = Minimap:GetEffectiveScale()
			LZ.settings.minimap.angle = math.atan2(py / scale - my, px / scale - mx)
			placeButton()
		end)
	end)
	button:SetScript("OnDragStop", function(self) self:SetScript("OnUpdate", nil) end)

	button:SetScript("OnEnter", function(self)
		GameTooltip:SetOwner(self, "ANCHOR_LEFT")
		GameTooltip:AddLine("Leeroylink", 1, 0.82, 0)
		for _, mod in ipairs(LZ.moduleList) do
			if mod.enabled and mod.TooltipLines then
				local ok, lines = pcall(mod.TooltipLines, mod)
				if ok and type(lines) == "table" then
					for _, l in ipairs(lines) do GameTooltip:AddLine(l, 1, 1, 1) end
				end
			end
		end
		GameTooltip:AddLine(" ")
		GameTooltip:AddLine(T("Linksklick: Fenster · Rechtsklick: Einstellungen", "Left-click: window · Right-click: settings"), 0.6, 0.6, 0.6)
		GameTooltip:AddLine(T("Shift-Klick: UI neu laden · Ziehen: verschieben", "Shift-click: reload UI · Drag: move"), 0.6, 0.6, 0.6)
		GameTooltip:Show()
	end)
	button:SetScript("OnLeave", function() GameTooltip:Hide() end)
end

function UI:UpdateMinimap()
	self:BuildMinimap()
	if not button then return end
	placeButton()
	if LZ.settings.minimap.hide then button:Hide() else button:Show() end
end

function UI:Init()
	self:UpdateMinimap()
end
