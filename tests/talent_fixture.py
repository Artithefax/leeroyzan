"""Talent data of the WoW Forever shaman in the format of Wowhead's talent calculator data file
(https://nether.wowhead.com/forever/de/data/talents-classic), shortened to what Leeroyzan reads."""
import json

# tree id -> rows of (id, row, col, max rank, spell, icon, English name, German name, [(required talent, points)])
SHAMAN = {
    261: [
        (104773, 0, 1, 5, 16039, "spell_nature_wispsplode", "Convection", "Konvektion", []),
        (104772, 0, 2, 5, 16035, "spell_nature_earthshock", "Concussion", "Erschütterung", []),
        (104769, 1, 0, 3, 30160, "spell_fire_elementaldevastation", "Elemental Devastation", "Elementarverwüstung", []),
        (104767, 1, 1, 5, 16040, "spell_frost_frostward", "Reverberation", "Nachklingen", []),
        (104771, 1, 2, 3, 16578, "spell_lightning_lightningbolt01", "Elemental Alacrity", "Elementare Geschwindigkeit", []),
        (104770, 1, 3, 3, 16038, "spell_fire_immolation", "Call of Flame", "Ruf der Flamme", []),
        (104768, 2, 0, 1, 16164, "spell_shadow_manaburn", "Elemental Focus", "Elementarfokus", []),
        (104765, 2, 1, 3, 28996, "spell_nature_spiritarmor", "Elemental Warding", "Schutz der Elemente", []),
        (104764, 3, 0, 2, 16086, "spell_fire_sealoffire", "Trial by Fire", "Feuerprobe", []),
        (104763, 3, 1, 3, 29062, "spell_nature_eyeofthestorm", "Eye of the Storm", "Auge des Sturms", []),
        (104762, 3, 3, 1, 1222988, "spell_nature_stranglevines", "Earthbound", "Erdgebunden", []),
        (104761, 4, 0, 2, 28999, "spell_nature_stormreach", "Elemental Reach", "Elementare Reichweite", []),
        (104760, 4, 1, 1, 16120, "spell_nature_callstorm", "Call of Thunder", "Ruf des Donners", []),
        (104759, 4, 2, 3, 408438, "spell_nature_lightningoverload", "Lightning Overload", "Blitzschlag-Überladung", [(104771, 3)]),
        (104766, 5, 2, 5, 16089, "spell_fire_volcano", "Elemental Fury", "Elementarfuror", [(104759, 3)]),
        (104758, 6, 1, 1, 16166, "spell_nature_unrelentingstorm", "Lightning Mastery", "Blitzbeherrschung", [(104760, 1)]),
    ],
    262: [
        (104739, 0, 1, 5, 16182, "spell_nature_magicimmunity", "Improved Healing Wave", "Verbesserte Welle der Heilung", []),
        (104729, 0, 2, 5, 16179, "spell_frost_manarecharge", "Tidal Focus", "Gezeitenfokus", []),
        (104734, 1, 0, 3, 1223033, "spell_nature_sleep", "Mindfulness", "Achtsamkeit", []),
        (104736, 1, 1, 3, 29187, "spell_nature_healingtouch", "Natural Grace", "Natürliche Anmut", []),
        (104735, 1, 2, 5, 16173, "spell_nature_moonglow", "Totemic Focus", "Totemfokus", []),
        (104737, 1, 3, 2, 16184, "spell_nature_reincarnation", "Improved Reincarnation", "Verbesserte Reinkarnation", []),
        (104731, 2, 0, 3, 16176, "spell_nature_undyingstrength", "Ancestral Healing", "Heilung der Ahnen", []),
        (104733, 2, 1, 3, 16181, "spell_nature_healingwavelesser", "Healing Focus", "Heilfokus", []),
        (104732, 2, 2, 1, 408510, "ability_shaman_watershield", "Water Shield", "Wasserschild", []),
        (104738, 3, 0, 5, 16194, "spell_nature_tranquility", "Tidal Mastery", "Gezeitenbeherrschung", []),
        (104730, 3, 1, 5, 16187, "spell_nature_manaregentotem", "Restorative Totems", "Regenerationstotems", []),
        (104728, 3, 2, 1, 16190, "spell_frost_summonwaterelemental", "Mana Tide Totem", "Totem der Manaflut", []),
        (104727, 4, 1, 3, 29206, "spell_nature_healingway", "Healing Way", "Pfad der Heilung", []),
        (104726, 4, 2, 1, 16188, "spell_nature_ravenform", "Nature's Swiftness", "Schnelligkeit der Natur", []),
        (104725, 5, 2, 5, 16178, "spell_frost_wizardmark", "Purification", "Läuterung", []),
        (104724, 6, 1, 1, 408521, "spell_nature_riptide", "Riptide", "Springflut", [(104727, 3)]),
    ],
    263: [
        (104757, 0, 0, 2, 16043, "spell_nature_stoneclawtotem", "Earth's Grasp", "Griff der Erde", []),
        (104753, 0, 1, 5, 16255, "ability_thunderbolt", "Thundering Strikes", "Donnernde Stöße", []),
        (104756, 0, 2, 5, 17485, "spell_shadow_grimward", "Ancestral Knowledge", "Wissen der Ahnen", []),
        (104754, 1, 0, 2, 16258, "spell_nature_stoneskintotem", "Guardian Totems", "Wächtertotems", []),
        (104755, 1, 1, 3, 415140, "spell_nature_mentalquickness", "Mental Dexterity", "Geistige Gewandtheit", []),
        (104751, 1, 2, 3, 16261, "spell_nature_lightningshield", "Improved Lightning Shield", "Verbesserter Blitzschlagschild", []),
        (104750, 2, 0, 3, 16266, "spell_fire_flametounge", "Elemental Weapons", "Elementarwaffen", []),
        (104749, 2, 2, 1, 1223030, "spell_nature_elementalabsorption", "Shamanistic Focus", "Schamanistischer Fokus", []),
        (104748, 2, 3, 3, 16254, "spell_nature_mirrorimage", "Anticipation", "Vorahnung", []),
        (104746, 3, 0, 5, 16252, "spell_holy_devotion", "Toughness", "Zähigkeit", []),
        (104747, 3, 1, 5, 16256, "ability_ghoulfrenzy", "Flurry", "Schlaghagel", [(104755, 3)]),
        (104743, 3, 2, 1, 17364, "ability_shaman_stormstrike", "Stormstrike", "Sturmschlag", []),
        (104752, 3, 3, 2, 16262, "spell_nature_spiritwolf", "Improved Ghost Wolf", "Verbesserter Geisterwolf", []),
        (104745, 4, 0, 1, 16268, "ability_parry", "Spirit Weapons", "Waffen der Geister", []),
        (104744, 4, 1, 2, 30812, "spell_nature_sleep", "Mental Quickness", "Geistige Schnelligkeit", []),
        (104742, 4, 2, 2, 1223031, "spell_shaman_improvedstormstrike", "Improved Stormstrike", "Verbesserter Sturmschlag", [(104743, 1)]),
        (104741, 5, 2, 5, 408498, "spell_shaman_maelstromweapon", "Maelstrom Weapon", "Waffe des Mahlstroms", []),
        (104740, 6, 1, 1, 425336, "spell_nature_bloodlust", "Rage of the Farseer", "Zorn des Scharfsehers", [(104744, 2)]),
    ],
}
# The build from Wowhead's enhancement shaman leveling guide (18/25/8) and its skill order
GUIDE_HASH = "vkndmh05330310201-0520303110212122-053_t0"
GUIDE_ORDER = "1BEcchGjpnpmmSRq2BC0BFccgcdddJm"


def talents_js(hash_version: str = "vkndmh", old_layout: bool = True) -> str:
    talents, layout = {}, {}
    for tab, rows in SHAMAN.items():
        talents[str(tab)] = {}
        for tid, row, col, mx, spell, icon, en, de, req in rows:
            talents[str(tab)][str(tid)] = {
                "id": tid, "row": row, "col": col, "icon": icon, "name": de, "nameEnus": en, "ranks": [spell] * mx,
                "definition": 1, "descriptions": {str(i + 1): f"{de}: Rang {i + 1}." for i in range(mx)},
                "requires": [{"id": r, "qty": q} for r, q in req], "requiredPoints": row * 5}
        # an older layout: the same talents, but the first one of every tree was called differently and came last
        ordered = sorted(rows, key=lambda r: (r[1], r[2]))
        layout[str(tab)] = [[r[1], r[2], r[3], r[4], r[6], r[1] * 5, []] for r in ordered[1:]] + \
                           [[9, 0, 1, 1, "Removed Talent", 45, []]]
    data = {"glyphs": {}, "talents": talents, "trees": {str(t): {"id": t} for t in SHAMAN}, "hashVersion": hash_version,
            "hashLayouts": {"v2": [layout]} if old_layout else {}, "abilities": {}}
    return 'WH.setPageData("wow.talentCalcClassic.classicplus.data", ' + json.dumps(data, ensure_ascii=False) + ");\n"
