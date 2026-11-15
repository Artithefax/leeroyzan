# Changelog

The section of a version becomes the text of its GitHub release automatically
(`tools/release_notes.py`, used by the *Build release exe* workflow).


## 2.2.3

### Leeroylink 0.8.0: a new look in the game
- **The window looks like the game's own.** Leeroylink now uses Blizzard's window templates as WoW Forever draws them: portrait frame with the Leeroylink emblem, tabs at the bottom, quest-log parchment for the pages, the game's list style on the left. Text is set in dark ink on the parchment.
- **Tabs instead of one long list:** *Overview*, *Session* (session log, loot log, screenshots), *Quests* (quest companion, checklists, notes), *Characters* (alts, recipes, AH prices), *Addons* (updates, error log, load status, profiles, wishlist, resources) and *Settings*. The overview shows what every part knows right now, grouped like the tabs.
- **The quest companion** has the same look: portrait frame, parchment, buttons in the button bar.
- **Banners:** a golden bar at the top of the screen with icon and sound – for news from Leeroyzan after login (updates, changelogs), the first error of an addon in a session, a completed quest chain and every boss kill. Click a banner to open the matching page. *Settings → Display* switches banners and sounds off; `/lz banner` shows a test banner.
- **Own minimap button** with the Leeroylink emblem; window sounds like the game's (open, close, tabs, checkboxes).
- The window remembers its position. `/lz ui` tells which Blizzard templates were used – if a future client lacks one, Leeroylink falls back to the classic dialog look.
- After updating, restart the game once (not just `/reload`): WoW only finds the new emblem image after a restart.

## 2.2.2

### Wowhead: much more in the preview
- Besides the tooltip, the preview now shows what the Wowhead page knows: **quick facts** (price, level, classification, start and end of a quest, patch …) and **where it comes from or what it is for** – *dropped by* (with drop chance, level and zone), *sold by* (with price), *reward from*, *contained in*, *reagent for*, *objective of*, an NPC's *loot* and *abilities*, what a node *yields*, and more. Up to five entries per list, sorted by drop chance; chances from very few observations are marked and come last.
- **Click an entry** (a vendor, a mob, a quest …) to look it up – it is put at the top of the results.
- Zone names come from QuestieDB and your characters (Leeroylink) when available.
- *Discord ↗* on the Wowhead page now also sends the quick facts and the top sources.

## 2.2.1

### New: share on Discord
- **A *Discord ↗* button wherever there is something to share:** talent builds (points per tree, every talent with its rank, the start of the skill order, link to the Wowhead talent calculator), saved guides (with links to the builds inside), Wowhead search results with their tooltip and icon, quests from QuestieDB, characters (gold only if you tick it) and addon lists.
- **Addon lists** arrive with links to CurseForge and GitHub *and* the download-list code. Friends copy the code into *Share → Receive* in their Leeroyzan to install everything. Long lists are split into several messages. Single addons: right click in the addon list → *Share on Discord …*.
- **Preview and comment:** before anything is sent you see what will appear in Discord and can add a line of your own.
- **Settings → Discord:** an optional channel of its own for shared posts (otherwise the session channel) and your name under shared posts. `@everyone`, `@here` and other mentions in a comment are never triggered.

### Fixed
- On the *Builds* page a long status text no longer pushes the buttons out of view.

## 2.2.0

### Discord
- **Every new session is posted, not only the last one.** If several sessions were saved at once (two characters, or Leeroyzan was closed while you played), they are sent oldest first – at most the five newest, and never the same session twice.
- **Milestones in the message:** visited dungeons and raids, discovered areas and **new personal records** of the character (most experience, biggest hit, longest session …; shown once a character has three earlier sessions). A level-up is marked in the title.
- The message has the colour of the character's class.
- **New: your Discord profile shows that you are playing** (Rich Presence, *Settings → Discord*, off by default). While WoW runs, Discord shows "Playing Leeroyzan – WoW Forever" with the time played and, if you like, the character played last with level and class. Leeroyzan talks to the Discord app on your PC directly – no bot, no token, nothing is sent by Leeroyzan over the internet. The status disappears when the game or Leeroyzan closes. Character and level are as fresh as the last time the game saved Leeroylink's data (logout or `/reload`).
- If Discord asks to slow down (HTTP 429), Leeroyzan waits as long as Discord says and tries again. A deleted webhook is explained in plain words.

## 2.1.0

### New: Builds – talent planner and guides
- **Talent planner with the original trees from Wowhead.** The new *Builds* page shows the three talent trees of a class the way Wowhead's talent calculator does – icons, backgrounds, arrows and rank counters – for WoW Forever (with its changed talents), Classic, Burning Crusade and Wrath. Left click spends a point, right click takes it back, Shift does all ranks at once; the rules of the game (points per row, required talents, point limit) are checked.
- **Builds from Wowhead and back.** Paste a talent calculator link (`…/talent-calc/shaman/…`) and the build opens in the planner, including the order in which the points are spent. *Copy link* and *Open on Wowhead* produce the same link again.
- **Skill order.** Next to the trees you see at which level each point is spent – handy for leveling builds.
- **Saved builds.** Give a build a name and pick it again later; the last build per game version is remembered.
- **Guides, saved for offline reading.** Paste the link of a Wowhead guide and Leeroyzan stores it in the data folder and shows it as text with headings, lists, tables and links to spells, items and quests. Talent builds embedded in a guide open in the planner with one click. *Refresh* fetches the current version.
- Talent data, icons and backgrounds are downloaded from Wowhead once and kept in the data folder (`wowhead`), so the planner also works offline afterwards.

### Wowhead
- The Wowhead search has a *WoW Forever* database now.

## 2.0.1

### Fixed
- `setup.bat` works again with an installed Python ("Das Sprungziel - with_python wurde nicht gefunden"). It now prefers Python 3.12, the version the releases are built with.

### Crash diagnostics
- If Leeroyzan closes unexpectedly, the cause is now recorded: hard crashes go to `crash.log` in the data folder (with the state of every thread), errors in the window and in background tasks go to `manager.log`.
- On the next start Leeroyzan tells you that the last session ended unexpectedly and opens the data folder on request.

## 2.0.0

**The big performance and stability update.** Leeroyzan 2.0 comes with Leeroylink 0.7.0.

### Faster
- Refreshing the addon list takes a few milliseconds instead of a quarter second: `.toc` files are cached by size and date (also across restarts), and the huge data `.toc` of QuestieDB is read only after it changed.
- The window opens faster and stays responsive: the first addon scan, the quest database, the reward index and the auction house rows are prepared in the background.
- Update checks run six requests at once. CurseForge addons are checked with a single batch request first; only projects that changed since the last check need their own request. GitHub answers are cached with ETags.
- The game process list is read directly from Windows instead of starting `tasklist`.
- The `.exe` unpacks about 700 fewer files on every start (unused Tcl time zone and date data).

### Safer
- **Updates swap folders instead of deleting first.** The new version is unpacked next to the AddOns folder and swapped in; if anything fails (a locked file, a full disk), the old version stays. Leftovers of an interrupted update are restored on the next start.
- **Undo keeps the old version by moving it, not copying it** – updates of large addons no longer copy hundreds of megabytes. The settings show how much space undo versions take; versions of removed addons and those older than 60 days are cleaned up automatically.
- **Your CurseForge and GitHub links are no longer lost** when the WoW drive is briefly unavailable: links without a folder are parked and come back when the folder does.
- API key, GitHub token and Discord webhook are stored encrypted (Windows data protection, bound to your Windows account). On another PC Leeroyzan asks you to enter them again.
- Tokens and keys are never sent along when a download is redirected to another server.
- Prepared for code signing: once the release is signed, the updater only accepts a new version from the same publisher.

### Easier to use
- Checking for updates or searching no longer blocks other actions – you can start the game while Leeroyzan checks. Running background tasks are shown in the status bar.
- If WoW closes right after starting (Battle.net is updating or repairing the game – "container locked"), Leeroyzan explains why and offers to open Battle.net.
- The sidebar is grouped and adapts to small windows, so all pages and the Play button always fit.
- New shortcuts: F5 refreshes, Ctrl+F jumps to the search of the current page, Del removes the selected addons (after asking), Ctrl+1 … Ctrl+9 switch pages, Ctrl+, opens the settings.

### Leeroylink 0.7.0
- The quest data now lives in its own load-on-demand addon **Leeroylink_Quests** (written by Leeroyzan) and is loaded only when the quest companion is used for the first time.
- Target, nameplates and boss frames are only checked in and right after combat.
- On clients without a readable combat log, Leeroylink stops listening to it.

### Under the hood
- The code is split into the package `leeroy/` (logic) and `leeroy/ui/` (window); `leeroyzan.py` is just the starter.
- Every release is built only after all tests pass (logic, Leeroylink scenario, window smoke test, translations, code check), with pinned build tools, and the finished `.exe` runs a self-test before it is uploaded. "Run workflow" creates the release as a draft and publishes it only when everything is attached.
