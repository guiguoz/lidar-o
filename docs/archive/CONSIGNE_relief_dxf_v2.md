# Consigne Claude Code — Relief DXF → `.omap` (v2)

> Remplace la première version de cette consigne, qui contenait des correspondances de symboles
> supposées et ignorait plusieurs inconnues. Ne pas l'utiliser.
>
> Fait suite au jalon Phase 7 végétation : `grimbosq_veg.omap` s'ouvre dans OOM, géoréférencé,
> symboles corrects (86/89/93), cibles FFCO atteintes sur les trois classes.

---

## Étape 0 — Inventaire, avant tout le reste

Cinq minutes, et le résultat conditionne toutes les étapes suivantes. **Rien à écrire comme
code de production ici.**

1. **Combien de DXF, pour combien de dalles ?** `docs/etat_existant.md` mentionne cinq fichiers
   (`out2.dxf`, `c2g.dxf`, `c3g.dxf`, `dotknolls.dxf`, `formlines.dxf`), mais Karttapullautin
   traite dalle par dalle et n'a tourné que sur une dalle en Phase 0. Sur les six dalles de
   Grimbosq : les DXF existent-ils pour toutes ? Sont-ils fusionnés ou séparés ?
   → Si une seule dalle est couverte, le livrable de cette consigne ne portera que sur elle.
   Le dire explicitement plutôt que de produire une carte partielle sans prévenir.

2. **Le mapping existe-t-il déjà ?** La consigne CRT précédente demandait de produire un tableau
   calques DXF ↔ codes ISOM comme livrable. Si `assets/kp_crt.crt` a été déposé et que ce tableau
   figure dans `docs/etat_existant.md`, **l'étape 2 ci-dessous se réduit à le lire** — ne pas
   refaire le travail.

3. **Calques réels** présents dans chaque fichier, comparés à la liste de `etat_existant.md`.
   Tout écart = mapping cassé silencieusement (risque signalé au plan v3, Phase 4).

4. **Volume.** Nombre d'entités par calque, et estimation du nombre d'objets `.omap` résultant.
   Ordre de grandeur attendu : des courbes à 5 m d'intervalle sur 600 ha peuvent produire des
   dizaines de milliers d'objets, contre 2225 pour la végétation actuelle.
   → **Si le total dépasse ~30 000 objets, s'arrêter et rapporter** avant d'écrire quoi que ce
   soit. Un `.omap` que OOM ne peut plus manipuler n'est pas un livrable, et la décision
   (filtrer ? séparer en fichiers ? réduire l'intervalle ?) doit être prise en connaissance
   de cause.

5. **Géoréférencement.** Étendue (bbox) de chaque DXF, comparée à l'emprise Grimbosq :
   X 448000–450001, Y 6886000–6889001 (Lambert 93). Karttapullautin travaille parfois avec une
   origine locale de dalle. Si les coordonnées ne correspondent pas, **s'arrêter et rapporter
   l'écart observé** (origine locale ? autre CRS ? décalage constant ?) — ne pas corriger à
   l'aveugle.

6. **Nature des géométries.** Les polylignes DXF sont-elles en segments droits, ou contiennent-
   elles des arcs / splines / bulges ? Si oui, leur conversion en coordonnées `.omap` par
   segments droits perdra le lissage que Karttapullautin a produit — à signaler, car cela entre
   en conflit avec la règle « ne pas retoucher les courbes » (voir plus bas).

**Livrable de l'étape 0** : un rapport court répondant aux six points. Les étapes suivantes ne
démarrent qu'après.

---

## Étape 1 — Mapping calque → code ISOM

**Si le tableau existe déjà (étape 0.2), le lire et passer à l'étape 2.**

Sinon, l'établir depuis la documentation Karttapullautin ou le CRT, **pas par déduction sur les
noms de calques**. Les correspondances ne sont pas évidentes :
- `contour_intermed` peut désigner une courbe intermédiaire ordinaire (101) ou une courbe de
  forme (103) — deux symboles cartographiquement très différents.
- `cliff2` / `cliff3` : falaise franchissable (202) ou infranchissable (201) ? Dépend de la
  convention KP.
- `depression` : courbe fermée avec tiret de pente, ou symbole de petite dépression (111) ?
  Le choix peut dépendre de la taille, auquel cas le seuil doit venir de la doc, pas d'une
  supposition.
- `dotknoll` est un **point**, pas une ligne — type d'objet différent (voir étape 2).

**Règle en cas de doute : signaler, ne pas choisir.** Si une correspondance reste incertaine
après consultation des sources, mapper vers le symbole le moins engageant et le lister dans le
rapport. Un cartographe corrige plus facilement une falaise sous-classée qu'une falaise inventée.

Le mapping va dans un fichier externe (même logique que `scripts/mappings/*.yaml`), jamais en
dur dans le code.

---

## Étape 2 — Extension de `omap_writer.py`

**Ne pas toucher au module végétation.** Il fonctionne, ses tests sont verts. Ajouter, ne pas
refactorer.

**Lignes** — même structure que les surfaces (`<object type="1">`), même format de coordonnées.
Différence critique : **le flag de fermeture**. Une courbe de niveau ouverte n'a pas de flag 2
sur son dernier point ; une courbe fermée (butte, dépression) en a un, comme une surface.
Se tromper produit un fichier qui s'ouvre normalement mais s'affiche faux — invisible aux tests
structurels.

**Points** — structure à vérifier sur un `.omap` de référence contenant des symboles ponctuels
(`sainte_anne.omap` en a : buttes, trous, arbres remarquables) **avant** d'écrire quoi que ce
soit. Ne pas supposer le format.

---

## Étape 3 — Assemblage

`write_omap` accepte les trois familles (surfaces, lignes, points) dans un même appel et produit
un fichier unique. L'ordre de dessin suit l'ordre des symboles dans le `.omap`, pas celui des
objets — rien de particulier à gérer si les codes ISOM sont corrects.

Le compteur `<objects count="N">` doit refléter le total toutes familles confondues.

---

## Tests

- **Mapping** : un calque inconnu → échec explicite. Jamais de symbole par défaut silencieux.
  Le bug `406.1` (symboles à bandes au lieu d'aplats, 17 tests verts) a montré ce que coûte un
  mapping qui « trouve quand même quelque chose ».
- **Golden ligne ouverte** : polyligne de 3 points → objet sans flag 2, count=3.
- **Golden ligne fermée** : anneau → dernier point avec flag 2.
- **Golden point** : un point → type et count conformes à ce qui a été relevé à l'étape 2.
- **Non-régression végétation** : tous les tests existants restent verts.
- **Fichier parseable**, compteur exact.

⚠️ **Limite connue de ces tests** : ils vérifient la structure XML produite, pas son
interprétation par OOM. Le bug `406.1` est passé à travers 17 tests verts. Les points que seul
l'œil peut trancher sont listés ci-dessous — ils ne sont pas optionnels.

---

## Étape 4 — Contrôle humain 🧑

Claude Code ne peut pas ouvrir OOM. Produire le fichier et **s'arrêter**.

Points à vérifier, dans cet ordre :

1. **Le fichier s'ouvre**, et reste manipulable (navigation, zoom) à ce volume d'objets.
2. **Superposition** : les courbes tombent-elles au bon endroit par rapport à la végétation ?
   (test réel du géoréférencement DXF)
3. **Courbes fermées** : buttes et dépressions s'affichent-elles comme des boucles fermées, ou
   comme des lignes ouvertes ? *C'est le point que les tests ne peuvent pas couvrir.*
4. **Courbes maîtresses** : apparaissent-elles bien une sur cinq, plus épaisses ?
5. **Symboles** : les falaises et buttes ont-elles l'apparence attendue, ou des variantes
   inattendues (le piège `406.1`) ?
6. **Plausibilité** : le relief ressemble-t-il au terrain, ou y a-t-il du bruit manifeste ?

---

## Ce qu'il ne faut pas faire

- **Ne pas simplifier ni lisser les courbes.** Karttapullautin les a déjà généralisées ; toute
  retouche dégraderait un travail calibré (plan v3, Phase 5 : câblage, pas d'algorithme).
  *Exception à signaler, pas à trancher seul* : si l'étape 0.6 révèle des arcs ou splines, leur
  conversion en segments est une perte inévitable — rapporter le compromis avant de procéder.
- **Ne pas inventer de correspondance de symbole** en cas de doute.
- **Ne pas produire un fichier au-delà du seuil de volume** sans en avoir discuté.
- **Ne pas toucher au module végétation.**
