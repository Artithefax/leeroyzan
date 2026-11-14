"""A shortened Wowhead guide page (structure as served by wowhead.com/forever/de/guide/…)."""
import json

MARKUP = (
    "Welcome to the Wowhead Enhancement Shaman leveling guide for Forever!  This guide covers tips &amp; tricks.\r\n\r\n"
    "[center][wrapper width=80%]\r\n[nav]\r\n"
    "[nav-item=guide/classes/shaman/enhancement/overview-pve-DPS icon=inv_misc_spyglass_01]Spec Overview[/nav-item]\r\n"
    "[nav-item=guide/classes/shaman/enhancement/rotation icon=spell_holy_circleofrenewal_shadow]Rotation[/nav-item]\r\n"
    "[/nav][/wrapper][/center]\r\n\r\n\r\n\r\n[toc]\r\n\r\n"
    "[h2 type=bar toc=\"Leveling Overview\"]Leveling as an Enhancement Shaman[/h2]\r\n[pad]\r\n[pad]\r\n\r\n"
    "Enhancement Shamans are very flexible levelers [1]. Use [spell=2645] and [item=249398] early; see [url=https://example.org/x]this page[/url].\r\n\r\n"
    "[h2 toc=\"Best Builds\" type=bar]Best Talent Builds[/h2]\r\n[pad]\r\n"
    "Pick up [spell=16262 def=134213 rank=2] as soon as you can, then [b]always[/b] [i]keep[/i] going.\r\n\r\n"
    "[center][quote type=box][talent=shaman/vkndmh05330310201-0520303110212122-053_t0_r2/1BEcchGjpnpmmSRq2BC0BFccgcdddJm abilities=true][/quote][/center]\r\n\r\n"
    "[h3 toc=\"Mandatory Abilities\"]Mandatory Abilities[/h3]\r\n[pad]\r\n\r\n"
    "[center]\r\n[table class=grid width=40%]\r\n[tr background=black][td]Spell[/td][td]Rank[/td][/tr]\r\n"
    "[tr][td][spell=10414][/td][td]7[/td][/tr]\r\n[/table]\r\n[/center]\r\n"
    "[tabs name=\"Rotation\"]\r\n[tab name=\"Single-Target Rotation\"]\r\n[ol]\r\n[li]Keep [spell=2645] up[/li]\r\n[li]Use [quest=1522][/li]\r\n[/ol]\r\n[/tab]\r\n"
    "[tab name=\"AoE Rotation\"][ul][li]Totems[/li][/ul][/tab]\r\n[/tabs]\r\n[script]evil()[/script]"
)


def guide_html(markup: str = MARKUP) -> str:
    spells = {"2645": {"name_dede": "Geisterwolf", "icon": "spell_nature_spiritwolf"},
              "16262": {"name_dede": "Verbesserter Geisterwolf", "icon": "spell_nature_spiritwolf"},
              "10414": {"name_dede": "Erdschock", "icon": "spell_nature_earthshock", "rank_dede": "Rang 7"}}
    items = {"249398": {"name_dede": "Ikone aus poliertem Treibholz", "quality": 3, "icon": "spell_shaman_totemrecall"}}
    quests = {"1522": {"name_dede": "Ruf des Feuers", "icon": "quest-start"}}
    related = {"34910": {"name": "Enhancement Shaman DPS Guide", "category": 543, "url": "https://www.wowhead.com/forever/de/guide/x"}}
    return (
        '<!DOCTYPE html>\n<html lang="de-DE">\n<head>\n<title>Enhancement Shaman Leveling Guide - WoW Forever - Wowhead</title>\n'
        '<meta property="og:title" content="Enhancement Shaman Leveling Guide - WoW Forever">\n'
        '<meta property="og:description" content="How to quickly level to 60 as an Enhancement Shaman.">\n'
        '<link rel="canonical" href="https://www.wowhead.com/forever/guide/classes/shaman/enhancement/dps-leveling-tips">\n'
        "</head><body>\n<script>\n"
        f"WH.Gatherer.addData(100, 16, {json.dumps(related)});\n"
        '        WH.markup.printHtml(\n            WH.getPageData("wowhead-guid6af8ce5fc04c40-40902756"),\n'
        '            "interior-sidebar-related-markup",\n                    );\n    </script>\n'
        '<h1 class="heading-size-1">Enhancement Shaman Leveling Guide - WoW Forever</h1>\n'
        '<a href="/forever/de/author/Yebb">\n Von Yebb </a>\n'
        '<span class="guide-content-byline-changed">\n    Aktualisiert:     <span class="date-tip" title="vor 8 tagen">\n'
        "        06.11.2026    </span>\n</span>\n<script>\n"
        f"WH.Gatherer.addData(3, 16, {json.dumps(items)});\nWH.Gatherer.addData(5, 16, {json.dumps(quests)});\n"
        f"WH.Gatherer.addData(6, 16, {json.dumps(spells, ensure_ascii=False)});\n"
        f"    WH.markup.printHtml({json.dumps(markup).replace('/', chr(92) + '/')}, \"guide-body\", "
        '{"allow":30,"disabledEnvironments":{"ptr":false}});\n\n    WH.Page.Guide.initStyling();\n</script>\n</body></html>\n'
    )
