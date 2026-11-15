-- Skin.lua: Blizzard-style building blocks shared by every Leeroylink window.
-- WoW Forever uses Blizzard's modern panel templates with its own art (ButtonFrameTemplate,
-- PanelTabButtonTemplate, the QuestBG-Parchment atlas ...), so windows built from them look
-- exactly like the game's own. Every template and atlas is tried first; if one is missing
-- (another client, a future patch), a classic dialog-box look is used instead.
local ADDON, LZ = ...
local T = LZ.T

local Skin = {}
LZ.Skin = Skin

Skin.ICON = "Interface\\AddOns\\" .. ADDON .. "\\Media\\Icon"
Skin.ICON_FALLBACK = "Interface\\Icons\\Ability_Warrior_Charge"
Skin.used = {}   -- which template/atlas worked (shown by /lz ui)

local DIALOG_BACKDROP = {
	bgFile = "Interface\\DialogFrame\\UI-DialogBox-Background",
	edgeFile = "Interface\\DialogFrame\\UI-DialogBox-Border",
	tile = true, tileSize = 32, edgeSize = 32,
	insets = { left = 11, right = 12, top = 12, bottom = 11 },
}
local BACKDROP_TEMPLATE = _G.BackdropTemplateMixin and "BackdropTemplate" or nil

local function try(kind, name, parent, template)
	if not template then return nil end
	local ok, f = pcall(CreateFrame, kind, name, parent, template)
	if ok and f then return f end
	return nil
end

-- An atlas, if the client knows it (otherwise false and the texture is left alone).
function Skin.Atlas(tex, atlas, useSize)
	if not tex or not tex.SetAtlas then return false end
	local CT = _G.C_Texture
	if CT and CT.GetAtlasInfo and not CT.GetAtlasInfo(atlas) then return false end
	local ok, res = pcall(tex.SetAtlas, tex, atlas, useSize)
	return ok and res ~= false
end

function Skin.Sound(kit)
	if LZ.settings and LZ.settings.ui and LZ.settings.ui.sound == false then return end
	local id = _G.SOUNDKIT and _G.SOUNDKIT[kit]
	if id and _G.PlaySound then pcall(PlaySound, id) end
end

function Skin.UISettings()
	local s = LZ.settings
	if not s then return { banners = true, sound = true } end
	s.ui = type(s.ui) == "table" and s.ui or {}
	if s.ui.banners == nil then s.ui.banners = true end
	if s.ui.sound == nil then s.ui.sound = true end
	return s.ui
end

----------------------------------------------------------------------
-- Text on parchment: dark ink instead of the light colours of the dark windows
----------------------------------------------------------------------
local INK, TITLE = { 0.18, 0.11, 0.04 }, { 0.30, 0.13, 0.02 }
if _G.GetMaterialTextColors then
	local ok, text, title = pcall(GetMaterialTextColors, "Parchment")
	if ok and type(text) == "table" and text[1] then INK, TITLE = text, title end
end
Skin.INK, Skin.TITLE = INK, TITLE

local function inkHex(r, g, b)
	return string.format("%02x%02x%02x", math.floor(r * 255 + 0.5), math.floor(g * 255 + 0.5), math.floor(b * 255 + 0.5))
end
Skin.INK_HEX, Skin.TITLE_HEX = inkHex(INK[1], INK[2], INK[3]), inkHex(TITLE[1], TITLE[2], TITLE[3])

-- Colour codes made for a black background are darkened until they read well on parchment:
-- greys and white become ink, gold/yellow becomes the brown of quest titles, other colours keep their
-- hue at a much lower brightness (green -> dark green, blue -> dark blue ...). Besides |cffRRGGBB this also
-- handles the named colours of newer clients, as in item links: |cnIQ2:[Name]|r, |cnGREEN_FONT_COLOR:...|r.
local QUALITY_HEX = { [0] = "9d9d9d", "ffffff", "1eff00", "0070dd", "a335ee", "ff8000", "e6cc80", "00ccff", "00ccff" }
local PARCHMENT_LUM = 0.24

local function onParchmentRGB(r, g, b)
	local hi, lo = math.max(r, g, b), math.min(r, g, b)
	if hi - lo < 0.12 then                                      -- grey/white: ink, mid grey a lighter ink
		local k = hi < 0.7 and 0.55 or 0
		return INK[1] + (0.45 - INK[1]) * k, INK[2] + (0.40 - INK[2]) * k, INK[3] + (0.35 - INK[3]) * k
	end
	if r >= 0.7 and g >= 0.7 * r and b <= 0.45 then             -- gold and yellow (headings): quest-title brown
		return TITLE[1], TITLE[2], TITLE[3]
	end
	local lum = 0.299 * r + 0.587 * g + 0.114 * b
	if lum > PARCHMENT_LUM then
		local f = PARCHMENT_LUM / lum
		r, g, b = r * f, g * f, b * f
	end
	return r, g, b
end

local function hexRGB(hex)
	return tonumber(hex:sub(1, 2), 16) / 255, tonumber(hex:sub(3, 4), 16) / 255, tonumber(hex:sub(5, 6), 16) / 255
end

local function namedHex(name)
	local q = tonumber(name:match("^IQ(%d+)$"))
	if q then
		local c = _G.ITEM_QUALITY_COLORS and _G.ITEM_QUALITY_COLORS[q]
		if type(c) == "table" and c.r then return inkHex(c.r, c.g, c.b) end
		return QUALITY_HEX[q] or "ffffff"
	end
	local c = _G[name]
	if type(c) == "table" and c.GenerateHexColor then
		local ok, hex = pcall(c.GenerateHexColor, c)
		if ok and type(hex) == "string" and #hex >= 6 then return hex:sub(-6) end
	end
	return "ffffff"
end

function Skin.ParchmentHex(hex)
	return inkHex(onParchmentRGB(hexRGB(hex)))
end

function Skin.OnParchment(text)
	if type(text) ~= "string" then return text end
	text = text:gsub("|cn([%w_]+):", function(name) return "|cff" .. Skin.ParchmentHex(namedHex(name)) end)
	return (text:gsub("|c(%x%x)(%x%x%x%x%x%x)", function(a, hex) return "|c" .. a .. Skin.ParchmentHex(hex) end))
end

-- A scroll frame with the game's thin scroll bar (ScrollFrameTemplate + MinimalScrollBar), the bar just
-- inside the right edge; the old UIPanelScrollFrameTemplate only if the new one is missing.
function Skin.Scroll(parent, left, top, right, bottom)
	local scroll = try("ScrollFrame", nil, parent, "ScrollFrameTemplate")
	local bar = scroll and rawget(scroll, "ScrollBar")
	if scroll and type(bar) == "table" then
		Skin.used.scroll = "MinimalScrollBar"
		scroll:SetPoint("TOPLEFT", left, top)
		scroll:SetPoint("BOTTOMRIGHT", right - 14, bottom)
		bar:ClearAllPoints()
		bar:SetPoint("TOPLEFT", scroll, "TOPRIGHT", 6, -2)
		bar:SetPoint("BOTTOMLEFT", scroll, "BOTTOMRIGHT", 6, 2)
		if bar.SetHideIfUnscrollable then pcall(bar.SetHideIfUnscrollable, bar, true) end
	else
		Skin.used.scroll = "UIPanelScrollFrameTemplate"
		scroll = CreateFrame("ScrollFrame", nil, parent, "UIPanelScrollFrameTemplate")
		scroll:SetPoint("TOPLEFT", left, top)
		scroll:SetPoint("BOTTOMRIGHT", right - 22, bottom)
	end
	local content = CreateFrame("Frame", nil, scroll)
	content:SetSize(10, 10)
	scroll:SetScrollChild(content)
	return scroll, content
end

----------------------------------------------------------------------
-- Fonts
----------------------------------------------------------------------
function Skin.Text(parent, font, layer)
	local candidates = font == "title" and { "QuestTitleFont", "GameFontNormalLarge" }
		or font == "small" and { "QuestFontNormalSmall", "GameFontBlackSmall", "GameFontHighlightSmall" }
		or font == "light" and { "GameFontHighlight" }
		or font == "lightsmall" and { "GameFontHighlightSmall" }
		or font == "gold" and { "GameFontNormal" }
		or { "QuestFont", "GameFontBlack", "GameFontHighlight" }
	local fs
	for _, name in ipairs(candidates) do
		if _G[name] then fs = parent:CreateFontString(nil, layer or "ARTWORK", name); break end
	end
	fs = fs or parent:CreateFontString(nil, layer or "ARTWORK", "GameFontHighlight")
	if font ~= "light" and font ~= "lightsmall" and font ~= "gold" then
		local c = font == "title" and TITLE or INK
		fs:SetTextColor(c[1], c[2], c[3])
		if fs.SetShadowColor then fs:SetShadowColor(0, 0, 0, 0) end
	end
	fs:SetJustifyH("LEFT")
	fs:SetJustifyV("TOP")
	return fs
end

function Skin.Portrait(f)
	local c = rawget(f, "PortraitContainer") or (type(f.PortraitContainer) == "table" and f.PortraitContainer)
	local p = type(c) == "table" and c.portrait
	return type(p) == "table" and p or nil
end

----------------------------------------------------------------------
-- Window: portrait, title, close button, inset; movable, position remembered, closes with Escape
----------------------------------------------------------------------
function Skin.Window(name, title, w, h, opts)
	opts = opts or {}
	local f = try("Frame", name, UIParent, opts.portrait == false and "DefaultPanelTemplate" or "ButtonFrameTemplate")
	if f then
		Skin.used.window = "ButtonFrameTemplate"
		if f.SetTitle then f:SetTitle(title) elseif f.TitleText then f.TitleText:SetText(title) end
		local p = Skin.Portrait(f)
		if p then
			p:SetTexture(Skin.ICON)
			if not p:GetTexture() then p:SetTexture(Skin.ICON_FALLBACK) end
		end
		if _G.ButtonFrameTemplate_HideButtonBar and opts.buttonBar == false then pcall(ButtonFrameTemplate_HideButtonBar, f) end
		f.body = type(f.Inset) == "table" and f.Inset or f
	else
		Skin.used.window = "dialog"
		f = CreateFrame("Frame", name, UIParent, BACKDROP_TEMPLATE)
		if f.SetBackdrop then f:SetBackdrop(DIALOG_BACKDROP) end
		local head = f:CreateTexture(nil, "ARTWORK")
		head:SetTexture("Interface\\DialogFrame\\UI-DialogBox-Header")
		head:SetSize(300, 64)
		head:SetPoint("TOP", 0, 12)
		local t = f:CreateFontString(nil, "OVERLAY", "GameFontNormal")
		t:SetPoint("TOP", head, "TOP", 0, -14)
		t:SetText(title)
		f.TitleText = t
		local close = CreateFrame("Button", nil, f, "UIPanelCloseButton")
		close:SetPoint("TOPRIGHT", -6, -6)
		local body = CreateFrame("Frame", nil, f)
		body:SetPoint("TOPLEFT", 14, -30)
		body:SetPoint("BOTTOMRIGHT", -14, 38)
		f.body = body
	end
	f:SetSize(w, h)
	f:SetFrameStrata(opts.strata or "HIGH")
	f:SetToplevel(true)
	f:SetClampedToScreen(true)
	f:SetMovable(true)
	f:EnableMouse(true)
	f:RegisterForDrag("LeftButton")
	f:SetScript("OnDragStart", function(s) s:StartMoving() end)
	f:SetScript("OnDragStop", function(s)
		s:StopMovingOrSizing()
		if opts.save then
			local point, _, rel, x, y = s:GetPoint(1)
			opts.save({ point, rel, x, y })
		end
	end)
	local pos = opts.pos
	f:ClearAllPoints()
	if type(pos) == "table" and pos[1] then
		f:SetPoint(pos[1], UIParent, pos[2] or pos[1], pos[3] or 0, pos[4] or 0)
	else
		f:SetPoint(opts.anchor or "CENTER", UIParent, opts.anchor or "CENTER", opts.x or 0, opts.y or 0)
	end
	f:Hide()
	if _G.UISpecialFrames and name then table.insert(UISpecialFrames, name) end
	if opts.sounds ~= false then
		f:HookScript("OnShow", function() Skin.Sound(opts.openSound or "IG_CHARACTER_INFO_OPEN") end)
		f:HookScript("OnHide", function() Skin.Sound(opts.closeSound or "IG_CHARACTER_INFO_CLOSE") end)
	end
	return f
end

-- Parchment background inside a frame (the quest frame's paper)
function Skin.Parchment(parent)
	local bg = parent:CreateTexture(nil, "BACKGROUND", nil, 1)
	bg:SetAllPoints()
	if Skin.Atlas(bg, "QuestBG-Parchment") then
		Skin.used.parchment = "QuestBG-Parchment"
	else
		Skin.used.parchment = "colour"
		if bg.SetColorTexture then bg:SetColorTexture(0.86, 0.77, 0.58, 1) else bg:SetTexture(0.86, 0.77, 0.58, 1) end
	end
	return bg
end

-- A scrolling text page on parchment: frame.title, frame.desc and frame.text; :SetPage(title, desc, text)
function Skin.ParchmentPage(parent)
	local page = CreateFrame("Frame", nil, parent)
	page:SetAllPoints()
	Skin.Parchment(page)
	local scroll, content = Skin.Scroll(page, 18, -14, -8, 12)
	local title = Skin.Text(content, "title")
	title:SetPoint("TOPLEFT", 0, -2)
	local desc = Skin.Text(content, "small")
	desc:SetPoint("TOPLEFT", title, "BOTTOMLEFT", 0, -6)
	local text = Skin.Text(content)
	text:SetPoint("TOPLEFT", desc, "BOTTOMLEFT", 0, -10)
	if text.SetSpacing then text:SetSpacing(3) end
	page.scroll, page.content, page.title, page.desc, page.text = scroll, content, title, desc, text
	local last
	scroll:SetScript("OnSizeChanged", function()                -- the width is known only once the window is laid out
		if last then
			local pos = scroll.GetVerticalScroll and scroll:GetVerticalScroll() or 0
			page:SetPage(last[1], last[2], last[3])
			if scroll.SetVerticalScroll then scroll:SetVerticalScroll(pos) end
		end
	end)

	function page:SetPage(t, d, body)
		last = { t, d, body }
		local sw = scroll:GetWidth() or 0
		local w = (sw > 50 and sw or (self.defaultWidth or 400)) - 6
		content:SetWidth(w)
		for _, fs in ipairs({ title, desc, text }) do fs:SetWidth(w) end
		title:SetText(t or "")
		desc:SetText(d and Skin.OnParchment(d) or "")
		text:SetText(Skin.OnParchment(body or ""))
		local hgt = (title:GetStringHeight() or 0) + (desc:GetStringHeight() or 0) + (text:GetStringHeight() or 0) + 40
		content:SetHeight(math.max(20, hgt))
		if scroll.SetVerticalScroll then scroll:SetVerticalScroll(0) end
	end
	return page
end

----------------------------------------------------------------------
-- Tabs at the bottom edge (PanelTabButtonTemplate)
----------------------------------------------------------------------
function Skin.Tabs(frame, labels, onSelect)
	local name = frame:GetName()
	frame.Tabs = type(frame.Tabs) == "table" and frame.Tabs or {}
	local tabs = {}
	for i, label in ipairs(labels) do
		local tab = try("Button", name and (name .. "Tab" .. i), frame, "PanelTabButtonTemplate")
			or try("Button", name and (name .. "Tab" .. i), frame, "CharacterFrameTabButtonTemplate")
		if tab then
			Skin.used.tabs = "PanelTabButtonTemplate"
			local found = false                       -- the template adds itself to frame.Tabs (parentArray)
			for _, t in ipairs(frame.Tabs) do if t == tab then found = true end end
			if not found then frame.Tabs[#frame.Tabs + 1] = tab end
		else
			Skin.used.tabs = "button"
			tab = CreateFrame("Button", nil, frame, "UIPanelButtonTemplate")
			tab:SetSize(96, 24)
			frame.Tabs[#frame.Tabs + 1] = tab
		end
		tab:SetID(i)
		tab:SetText(label)
		tab:SetScript("OnClick", function(self)
			Skin.Sound("IG_CHARACTER_INFO_TAB")
			onSelect(self:GetID())
		end)
		tab:ClearAllPoints()
		if i == 1 then
			tab:SetPoint("TOPLEFT", frame, "BOTTOMLEFT", 12, 2)
		else
			tab:SetPoint("TOPLEFT", tabs[i - 1], "TOPRIGHT", 3, 0)
		end
		tabs[i] = tab
	end
	if _G.PanelTemplates_SetNumTabs and Skin.used.tabs == "PanelTabButtonTemplate" then
		pcall(PanelTemplates_SetNumTabs, frame, #tabs)
		for _, tab in ipairs(tabs) do
			if _G.PanelTemplates_TabResize then pcall(PanelTemplates_TabResize, tab, 0) end
		end
	end
	function frame:SelectTab(id)
		if _G.PanelTemplates_SetTab and Skin.used.tabs == "PanelTabButtonTemplate" then
			pcall(PanelTemplates_SetTab, self, id)
		else
			for i, tab in ipairs(tabs) do
				if i == id and tab.LockHighlight then tab:LockHighlight() elseif tab.UnlockHighlight then tab:UnlockHighlight() end
			end
		end
	end
	return tabs
end

----------------------------------------------------------------------
-- Category list (left side of a tab), like the game's settings list
----------------------------------------------------------------------
function Skin.List(parent, width, onSelect)
	local list = CreateFrame("Frame", nil, parent)
	list:SetPoint("TOPLEFT", 4, -4)
	list:SetPoint("BOTTOMLEFT", 4, 4)
	list:SetWidth(width)
	local bg = list:CreateTexture(nil, "BACKGROUND")
	bg:SetAllPoints()
	if bg.SetColorTexture then bg:SetColorTexture(0, 0, 0, 0.35) end
	list.buttons = {}
	function list:SetItems(items, selected)
		for i, item in ipairs(items) do
			local b = self.buttons[i]
			if not b then
				b = CreateFrame("Button", nil, self)
				b:SetSize(width - 8, 24)
				b:SetPoint("TOPLEFT", 4, -4 - (i - 1) * 26)
				b.label = b:CreateFontString(nil, "ARTWORK", "GameFontHighlight")
				b.label:SetPoint("LEFT", 10, 0)
				b.label:SetPoint("RIGHT", -6, 0)
				b.label:SetJustifyH("LEFT")
				b.sel = b:CreateTexture(nil, "BACKGROUND")
				b.sel:SetAllPoints()
				if not Skin.Atlas(b.sel, "Options_List_Active") and b.sel.SetColorTexture then b.sel:SetColorTexture(1, 0.82, 0, 0.18) end
				local hl = b:CreateTexture(nil, "HIGHLIGHT")
				hl:SetAllPoints()
				if not Skin.Atlas(hl, "Options_List_Hover") and hl.SetColorTexture then hl:SetColorTexture(1, 1, 1, 0.08) end
				b:SetScript("OnClick", function(s) Skin.Sound("U_CHAT_SCROLL_BUTTON"); onSelect(s.key) end)
				self.buttons[i] = b
			end
			b.key = item.key
			b.label:SetText(item.label)
			b.label:SetTextColor(item.off and 0.5 or 1, item.off and 0.5 or 1, item.off and 0.5 or 1)
			if item.key == selected then b.sel:Show(); b.label:SetTextColor(1, 0.82, 0) else b.sel:Hide() end
			b:Show()
		end
		for i = #items + 1, #self.buttons do self.buttons[i]:Hide() end
	end
	return list
end

function Skin.Button(parent, label, w, onClick)
	local b = CreateFrame("Button", nil, parent, "UIPanelButtonTemplate")
	b:SetSize(w or 120, 22)
	b:SetText(label)
	b:SetScript("OnClick", onClick)
	return b
end

----------------------------------------------------------------------
-- Banners: a golden bar at the top of the screen, with icon, sound and fade
----------------------------------------------------------------------
local banner, bannerAnim
local queue, showing = {}, false
local SHOW_TIME = 5

local function buildBanner()
	if banner then return end
	banner = CreateFrame("Frame", "LeeroylinkBanner", UIParent)
	banner:SetSize(520, 86)
	banner:SetPoint("TOP", UIParent, "TOP", 0, -150)
	banner:SetFrameStrata("HIGH")
	banner:Hide()
	local shade = banner:CreateTexture(nil, "BACKGROUND")
	shade:SetPoint("TOPLEFT", 0, -10)
	shade:SetPoint("BOTTOMRIGHT", 0, 10)
	if shade.SetColorTexture then shade:SetColorTexture(0, 0, 0, 0.55) end
	if Skin.Atlas(shade, "levelup-shadow-lower") then Skin.used.banner = "levelup" else Skin.used.banner = "colour" end
	local top = banner:CreateTexture(nil, "ARTWORK")
	top:SetPoint("TOPLEFT", 10, -8)
	top:SetPoint("TOPRIGHT", -10, -8)
	top:SetHeight(4)
	if not Skin.Atlas(top, "levelup-bar-gold") and top.SetColorTexture then top:SetColorTexture(1, 0.82, 0, 0.9) end
	local bottom = banner:CreateTexture(nil, "ARTWORK")
	bottom:SetPoint("BOTTOMLEFT", 10, 8)
	bottom:SetPoint("BOTTOMRIGHT", -10, 8)
	bottom:SetHeight(4)
	if not Skin.Atlas(bottom, "levelup-bar-gold") and bottom.SetColorTexture then bottom:SetColorTexture(1, 0.82, 0, 0.9) end
	local icon = banner:CreateTexture(nil, "ARTWORK")
	icon:SetSize(44, 44)
	icon:SetPoint("LEFT", 26, 0)
	banner.icon = icon
	local title = banner:CreateFontString(nil, "ARTWORK", _G.GameFontNormalHuge and "GameFontNormalHuge" or "GameFontNormalLarge")
	title:SetPoint("TOPLEFT", icon, "TOPRIGHT", 14, 2)
	title:SetPoint("RIGHT", -24, 0)
	title:SetJustifyH("LEFT")
	banner.title = title
	local text = banner:CreateFontString(nil, "ARTWORK", "GameFontHighlight")
	text:SetPoint("TOPLEFT", title, "BOTTOMLEFT", 0, -4)
	text:SetPoint("RIGHT", -24, 0)
	text:SetJustifyH("LEFT")
	banner.text = text
	banner:EnableMouse(true)
	banner:SetScript("OnMouseUp", function(self)
		if self.onClick then pcall(self.onClick) end
		self:Hide()
	end)

	-- fade in, hold, fade out
	local ag = banner.CreateAnimationGroup and banner:CreateAnimationGroup()
	if ag then
		local fadeIn = ag:CreateAnimation("Alpha")
		fadeIn:SetFromAlpha(0); fadeIn:SetToAlpha(1); fadeIn:SetDuration(0.35); fadeIn:SetOrder(1)
		local slide = ag:CreateAnimation("Translation")
		slide:SetOffset(0, -12); slide:SetDuration(0.35); slide:SetOrder(1)
		local hold = ag:CreateAnimation("Alpha")
		hold:SetFromAlpha(1); hold:SetToAlpha(1); hold:SetDuration(SHOW_TIME); hold:SetOrder(2)
		local fadeOut = ag:CreateAnimation("Alpha")
		fadeOut:SetFromAlpha(1); fadeOut:SetToAlpha(0); fadeOut:SetDuration(0.8); fadeOut:SetOrder(3)
		ag:SetScript("OnFinished", function() banner:Hide() end)
		bannerAnim = ag
	end
	banner:SetScript("OnHide", function()
		if bannerAnim then bannerAnim:Stop() end
		showing = false
		if #queue > 0 and C_Timer and C_Timer.After then C_Timer.After(0.4, Skin.NextBanner) end
	end)
end

function Skin.NextBanner()
	if showing or #queue == 0 then return end
	buildBanner()
	local b = table.remove(queue, 1)
	showing = true
	Skin.lastBanner = b
	banner.icon:SetTexture(b.icon or Skin.ICON)
	if not banner.icon:GetTexture() then banner.icon:SetTexture(Skin.ICON_FALLBACK) end
	banner.title:SetText(b.title or "")
	banner.text:SetText(b.text or "")
	banner.onClick = b.onClick
	banner:SetAlpha(1)
	banner:Show()
	Skin.Sound(b.sound or "UI_EPICLOOT_TOAST")
	if bannerAnim then
		bannerAnim:Play()
	elseif C_Timer and C_Timer.After then
		C_Timer.After(SHOW_TIME, function() banner:Hide() end)
	end
end

-- LZ.Skin.Banner{ title = ..., text = ..., icon = path, sound = SOUNDKIT name, onClick = fn }
function Skin.Banner(b)
	if type(b) ~= "table" or not Skin.UISettings().banners then return false end
	if #queue >= 5 then table.remove(queue, 1) end
	queue[#queue + 1] = b
	Skin.NextBanner()
	return true
end

LZ.coreCommands["ui"] = function()
	local parts = {}
	for k, v in pairs(Skin.used) do parts[#parts + 1] = k .. "=" .. tostring(v) end
	table.sort(parts)
	LZ:Print(T("Oberfläche: ", "Interface: ") .. (#parts > 0 and table.concat(parts, ", ") or T("noch nichts geöffnet", "nothing opened yet")))
end

LZ.coreCommands["banner"] = function()
	Skin.Banner({ title = "Leeroylink", text = T("So sehen Einblendungen aus. Klick schließt sie.", "This is what banners look like. Click to close."),
		sound = "UI_EPICLOOT_TOAST" })
end
