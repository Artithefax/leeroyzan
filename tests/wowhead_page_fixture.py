"""Ausschnitte echter Wowhead-Seiten (WoW Forever, deutsch, 15.11.2026), gekürzt auf wenige Einträge je Liste.

Nur die Teile, die Leeroyzan liest: die Schnellinfo (WH.markup.printHtml … infobox) und die Listen (new Listview).
Die Listen kommen in zwei Schreibweisen vor (mehrzeilig und einzeilig, data: [ und data:[), und manche Einträge
haben Schlüssel ohne Anführungszeichen (modes:{…}) – beides muss der Parser verkraften.
Für die Tests ergänzt: „Seltener Kobold“ (3 von 3 – zu wenig Daten) und „Hoggers Halskette“ (blaue Qualität).
"""

ITEM_2589 = r'''<html><head><title>Leinenstoff - Gegenstand - WoW Forever</title></head><body><script>
WH.markup.printHtml("[ul][li][url=\/forever\/de\/items?filter=217;1;0]Handwerksmaterial[\/url][\/li][li]Seite: Keins[\/li][li]Hinzugefügt in Patch [acronym=\"1.60.1.69876\"]1.60.1[\/acronym][\/li][li class=icon-db-link]Symbol: [icondb=132889 name=true][\/li][li]Englische: [copy button=false]Linen Cloth[\/copy][\/li][\/ul]", "infobox-contents-0", {});
new Listview({
    template: 'npc',
    id: 'dropped-by',
    name: WH.TERMS.droppedby,
    tabs: 'tabsRelated',
    parent: 'lkljbjkb574',
    hiddenCols: ['type'],
    extraCols: [Listview.extraCols.count, Listview.extraCols.percent, Listview.extraCols.popularity],
    sort: ['-percent', '-count', 'name'],
    computeDataFunc: Listview.funcBox.initLootTable,
        data: [{"classification":0,"displayName":"Koboldhilfsarbeiter","displayNames":["Koboldhilfsarbeiter"],"id":80,"location":[12],"maxlevel":4,"minlevel":3,"name":"Koboldhilfsarbeiter","names":["Koboldhilfsarbeiter"],"react":[-1,null],"type":7,"count":8613,"outof":29563,"personal_loot":0,"pctstack":null,"modes":{"0":{"count":8613,"outof":29563},"mode":[0]}},{"classification":0,"displayName":"Taschendieb der Defias","displayNames":["Taschendieb der Defias","Taschendiebin der Defias"],"id":94,"location":[12],"maxlevel":6,"minlevel":5,"name":"Taschendieb der Defias","names":["Taschendieb der Defias","Taschendiebin der Defias"],"react":[-1,-1],"type":7,"count":2467,"outof":7884,"personal_loot":0,"pctstack":"{1: 49.9797,2: 50.0203}","popularity":35},{"classification":0,"displayName":"Schmuggler der Defias","displayNames":["Schmuggler der Defias","Schmugglerin der Defias"],"id":95,"location":[40],"maxlevel":12,"minlevel":11,"name":"Schmuggler der Defias","names":["Schmuggler der Defias","Schmugglerin der Defias"],"react":[-1,-1],"type":7,"count":14688,"outof":43948,"personal_loot":0,"pctstack":"{1: 33.4763,2: 33.8712,3: 32.6525}","popularity":26},{"classification":4,"displayName":"Morgaine die Verschlagene","displayNames":["Morgaine die Verschlagene"],"id":99,"location":[12],"maxlevel":10,"minlevel":10,"name":"Morgaine die Verschlagene","names":["Morgaine die Verschlagene"],"react":[-1,null],"type":7,"count":61,"outof":201,"personal_loot":0,"pctstack":"{1: 57.377,2: 42.623}","popularity":292},{"classification":0,"displayName":"Seltener Kobold","id":7,"location":[12],"maxlevel":5,"minlevel":5,"name":"Seltener Kobold","type":7,"count":3,"outof":3}],
});
new Listview({
    template: 'object',
    id: 'contained-in-object',
    name: WH.TERMS.containedin,
    tabs: 'tabsRelated',
    parent: 'lkljbjkb574',
    hiddenCols: ['type'],
    extraCols: ['count', 'percent', 'popularity'],
    sort: ['-percent', 'name'],
    computeDataFunc: Listview.funcBox.initLootTable,
        data: [{"displayName":"Regelventil","id":61935,"location":[17],"name":"Regelventil","type":-9,"count":1,"outof":6,"pctstack":""},{"displayName":"Geldkassette der Allianz","id":3714,"location":[17],"name":"Geldkassette der Allianz","skill":1,"type":-5,"count":2,"outof":49,"pctstack":"{1: 50,3: 50}"}],
});
new Listview({
    template: 'spell',
    id: 'reagent-for',
    name: WH.TERMS.reagentfor,
    tabs: 'tabsRelated',
    parent: 'lkljbjkb574',
        data: [{"cat":11,"colors":[0,25,37,50],"creates":[2996,1,1],"displayName":"Leinenstoffballen","id":2963,"learnedat":25,"level":0,"name":"Leinenstoffballen","nskillup":1,"quality":1,"reagents":[[2589,2]],"schools":1,"skill":[197]},{"cat":9,"colors":[0,30,45,60],"creates":[1251,1,1],"displayName":"Leinenverband","id":3275,"learnedat":30,"level":0,"name":"Leinenverband","nskillup":1,"quality":1,"reagents":[[2589,1]],"schools":1,"skill":[129]},{"cat":0,"displayName":"Defiasverkleidung","id":5169,"level":0,"name":"Defiasverkleidung","reagents":[[2589,1]],"schools":1}],
});
new Listview({
    template: 'quest',
    id: 'objective-of',
    name: WH.TERMS.objectiveof,
    tabs: 'tabsRelated',
    parent: 'lkljbjkb574',
    data: [{"category":-141,"category2":4,"classs":2,"id":1644,"level":13,"name":"Der Foliant der Offenbarung","race":1,"reqclass":2,"reqlevel":12,"reqrace":1,"side":1,"xp":910},{"category":-161,"category2":4,"classs":128,"id":1961,"level":15,"name":"Materialsammlung","race":146,"reqclass":128,"reqlevel":15,"reqrace":146,"side":2,"xp":800}],
});
new Listview({
    template: 'item',
    id: 'see-also',
    name: WH.TERMS.seealso_stc,
    tabs: 'tabsRelated',
    parent: 'lkljbjkb574',
        data: [{"classs":7,"displayName":"Leinenstoffballen","id":2996,"level":10,"name":"Leinenstoffballen","quality":1,"slot":0,"source":[1,2],"subclass":5}],
});
</script><script>new Listview({
    data: lv_comments3,
    id: 'comments',
    name: WH.TERMS.comments,
    parent: lkljbjkb574,
    template: 'comment',
});</script></body></html>'''

ITEM_159 = r'''<script>
WH.markup.printHtml("[ul][li]Preis: [money=23-27][\/li][li]Seite: Keins[\/li][li]Abklingzeit: 1 sekunde[\/li][li][tooltip name=wowhead-guid6af9d6fbedbe08-70161102]Beim Benutzen verbraucht[\/tooltip][span tooltip=wowhead-guid6af9d6fbedbe08-70161102 class=tip]Verbrauchbar[\/span][\/li][li]Hinzugefügt in Patch [acronym=\"1.60.1.69876\"]1.60.1[\/acronym][\/li][li class=icon-db-link]Symbol: [icondb=132794 name=true][\/li][li]Englische: [copy button=false]Refreshing Spring Water[\/copy][\/li][\/ul]", "infobox-contents-0", {});
new Listview({
    template: 'quest',
    id: 'reward-from-q',
    name: WH.TERMS.rewardfrom,
    tabs: 'tabsRelated',
    parent: 'lkljbjkb574',
    extraCols: ['popularity'],
    sort: ['popularity'],
    data: [{"category":85,"category2":0,"id":8,"itemchoices":[[4604,5],[159,5]],"level":5,"name":"Ein Schurkenhandel","reprewards":[[68,25]],"reqlevel":1,"side":2,"xp":110,"popularity":189},{"category":85,"category2":0,"id":381,"itemchoices":[[3268,1],[3269,1],[3267,1],[5779,1]],"itemrewards":[[159,5]],"level":4,"name":"Der Scharlachrote Kreuzzug","race":146,"reprewards":[[68,100]],"reqlevel":2,"reqrace":146,"side":2,"xp":355,"popularity":184}],
});
new Listview({
    template: 'npc',
    id: 'sold-by',
    name: WH.TERMS.soldby,
    tabs: 'tabsRelated',
    parent: 'lkljbjkb574',
    hiddenCols: ['level', 'type'],
    extraCols: ['stock', Listview.funcBox.createSimpleCol('stack', 'stack', '10%', 'stack'), 'cost', 'popularity'],
    sort: ['popularity'],
            note: WH.sprintf(WH.TERMS.npcsfounddisplayed_format, 230, 200),
    _truncated: 1,
            data: [{"classification":0,"displayName":"Brog Hamfist","displayNames":["Brog Hamfist"],"id":151,"location":[12],"maxlevel":10,"minlevel":10,"name":"Brog Hamfist","names":["Brog Hamfist"],"react":[1,null],"tag":"Gemischtwaren","type":7,"stock":-1,"cost":[[26]],"stack":5,"popularity":161},{"classification":0,"displayName":"Bruder Danil","displayNames":["Bruder Danil"],"id":152,"location":[12],"maxlevel":5,"minlevel":5,"name":"Bruder Danil","names":["Bruder Danil"],"react":[1,null],"tag":"Gemischtwaren","type":7,"stock":-1,"cost":[[26]],"stack":5,"popularity":75}],
});
</script>'''

NPC_448 = r'''<script>
WH.markup.printHtml("[ul][li]Stufe: 11[\/li][li]Einstufung: Elite[\/li][li]Einstellung: [color=q10]A[\/color] [color=q10]H[\/color][\/li][li]Art: Humanoid[\/li][li]Wert: [tooltip name=wowhead-guid6af9d6e29eb294-75901252]Durchschnittlich geplünderte Geldmenge[\/tooltip][span tooltip=wowhead-guid6af9d6e29eb294-75901252 class=tip][money=27][\/span][\/li][li]Hinzugefügt in Patch [acronym=\"1.13.2.30406\"]1.13.2[\/acronym] \"Classic\"[\/li][li]Englische: [copy button=false]Hogger[\/copy][\/li][\/ul]", "infobox-contents-0", {});
new Listview({template: 'item', id: 'drops', name: WH.TERMS.drops, tabs: tabsRelated, parent: 'lkljbjkb574', extraCols: ['count', 'percent'],  showLootSpecs: 0,sort:['noteworthy', '-percent', 'name'], _totalCount: 2295, computeDataFunc: Listview.funcBox.initLootTable, data:[{"classs":0,"displayName":"Zähes Stockfleisch","flags2":24576,"id":117,"level":5,"name":"Zähes Stockfleisch","quality":1,"reqlevel":6,"slot":0,"source":[2,4,5,19,21,23],"subclass":5,"modes":{"mode":[0],"0":{"count":111,"outof":2295}},"count":111,"stack":[1,1],"outof":2295},{"classs":0,"displayName":"Schwacher Heiltrank","flags2":24576,"id":118,"level":5,"name":"Schwacher Heiltrank","quality":1,"reqlevel":10,"slot":0,"source":[1,2,4,16,19,21],"subclass":1,"count":28,"stack":[1,1],"outof":2295},{"classs":4,"displayName":"Hoggers Halskette","id":1800,"level":12,"name":"Hoggers Halskette","quality":3,"reqlevel":7,"slot":2,"count":30,"stack":[1,1],"outof":2295}]});
new Listview({template: 'spell', id: 'abilities', name: WH.TERMS.abilities, tabs: tabsRelated, parent: 'lkljbjkb574', visibleCols: ['schools'], hiddenCols: ['reagents', 'skill'], computeDataFunc: Listview.funcBox.initModeFilter, data: [{"cat":-8,"displayName":"Rüstung durchstechen","id":6016,"level":1,"name":"Rüstung durchstechen","schools":1,modes:{"mode":[0]}},{"cat":-8,"displayName":"Sturmattacke","id":6268,"level":1,"name":"Sturmattacke","rank":"Rang 1","schools":1,"envChange":{"status":"updated","labels":["values_changed"],"lines":["[values increased by [0,8%] und [1,6%]]"]},modes:{"mode":[0]}},{"cat":-8,"displayName":"Kopfnuss","id":6730,"level":10,"name":"Kopfnuss","schools":1,modes:{"mode":[0]}}]});
</script>'''

QUEST_176 = r'''<script>
WH.markup.printHtml("[ul][li]Stufe: 11[\/li][li]Benötigt Stufe 5[\/li][li]Art: Elite[\/li][li]Seite: [span class=icon-alliance]Allianz[\/span][\/li][li][icon name=quest-start]Anfang: [url=\/forever\/de\/object=68\/steckbrief]Steckbrief[\/url][\/icon][br][span=invisible][icon name=quest-start]Anfang: [\/icon][\/span][url=\/forever\/de\/object=156561\/steckbrief]Steckbrief[\/url][\/li][li][icon name=quest-end]Ende: [url=\/forever\/de\/npc=240\/marshal-dughan]Marshal Dughan[\/url][\/icon][\/li][li]Teilbar[\/li][li]Modus: [color=q10]5[\/color][small] &nbsp;[\/small][color=r1]7[\/color][small] &nbsp;[\/small][color=r2]9[\/color][small] &nbsp;[\/small][color=r3]14[\/color][small] &nbsp;[\/small][color=r4]17[\/color][\/li][li]Hinzugefügt in Patch [acronym=\"1.13.2.30406\"]1.13.2[\/acronym] \"Classic\"[\/li][li]Englische: [copy button=false]GESUCHT: \"Hogger\"[\/copy][\/li][\/ul]", "infobox-contents-0", {});
</script>'''
