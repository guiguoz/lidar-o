# Règles de généralisation cartographique CO (ISOM 2017-2)

> Document de référence pour le CO Generalization Engine (Phase 6).
> Échelle cible : 1:10 000. Convertir en m terrain = valeur_mm × 10.

## Validation requise — 3 sources

Ce document contient des **règles supposées**. Avant implémentation, valider contre :
1. **ISOM 2017-2 officiel** — contraintes minimales (§12 Vegetation, §1 General)
2. **Comportement OCAD** — paramètres de Remove Small Objects / Simplify / Generalize (indices d'expérience implicite)
3. **Cartes FFCO de haut niveau** — règles observées sur terrain réel (corpus à constituer)

L'ISOM donne les contraintes, pas l'algorithme. OCAD et les cartes réelles donnent l'algorithme.

## Corpus de calibration (Phase 5.5 — avant tout code de généralisation)

### Mini-corpus cible : 3–5 terrains variés

| Terrain | Intérêt |
|---|---|
| Grimbosq | feuillus normands, relief modéré |
| Terrain plantation / régénération dense | stress test végétation |
| Terrain rocheux | validation relief/rochers |
| Terrain semi-ouvert | gestion blanc/jaune/vert |
| Terrain très propre (forêt dégagée) | contrôle |

Extraits de 500 m × 500 m suffisent. **Ne pas calibrer sur Grimbosq seul** — biais normand.

### Ce qu'on mesure (histogrammes, pas seuils)

Les seuils dans ce document sont des **suppositions**. Les remplacer par des distributions mesurées sur cartes FFCO réelles :

**Polygones verts :**
- Histogramme des surfaces par décile (0-10 m², 10-20 m², 20-50 m², 50-100 m², …)
- Objectif : "95% des polygones < X m² sont supprimés sur les cartes réelles"

**Trous / enclaves :**
- Distribution des surfaces et largeurs minimales conservées

**Corridors :**
- Distribution des largeurs et longueurs présents sur la carte finale

**Complexité géométrique :**
- Nombre de sommets par polygone : brut HAG vs carte CO finale
- Indice de compacité (périmètre² / aire)
- Objectif : calibrer Douglas-Peucker et Chaikin sur écart réel (ex. 400 sommets → 40)

### La carte FFCO = test unitaire du moteur

Chaque sortie du CO Generalization Engine doit être comparée au corpus. Les cartes FFCO ne servent pas à entraîner un modèle ML — elles servent à **mesurer** si les règles produisent un résultat cohérent avec ce que ferait un cartographe humain.

### Outil Phase 5.5

Créer `scripts/measure_corpus.py` qui produit automatiquement ces statistiques sur :
- une carte FFCO (GeoJSON / Shapefile importé)
- la sortie HAG intermédiaire correspondante

Sortie : rapport JSON + histogrammes → alimente les paramètres de `config.yaml`.

---

## Principe fondamental

Une carte de CO n'est **pas** une carte fidèle. C'est une représentation volontairement déformée pour maximiser la lisibilité à vitesse élevée. Les règles ci-dessous encodent ce que fait un cartographe humain, pas ce qu'un SIG produit.

---

## §0 — Les 5 règles qui font 80 % de la généralisation

**Implémenter ces 5 règles en premier. Ne pas aller au-delà avant validation sur terrain réel.**

1. Suppression des petits polygones (seuil configurable par classe)
2. Suppression des petits trous / enclaves
3. Fusion des verts proches (distance de fusion configurable)
4. Fermeture des corridors trop étroits
5. Simplification + lissage Chaikin ×1

---

---

## 1. Tailles minimales par symbole végétation

| Symbole | Code ISOM | Taille mini terrain | Taille mini map |
|---|---|---|---|
| Terrain découvert (blanc) | 401 | ~50 m² | ~0.5 mm² |
| Végétation basse (jaune) | 402–403 | ~50 m² | ~0.5 mm² |
| Forêt dégagée (vert clair) | 406 | ~50 m² | ~0.5 mm² |
| Sous-bois difficile (vert moyen) | 407–408 | ~30 m² | ~0.3 mm² |
| Végétation très dense (vert foncé) | 410 | ~20 m² | ~0.2 mm² |

> ⚠️ Valeurs à confirmer — source ISOM 2017-2 §12 (Vegetation)

**Règle d'application :**
- Polygone < taille mini → **supprimer** ou **fusionner** avec classe adjacente dominante
- Ne jamais créer de polygone en dessous du seuil

---

## 2. Trous / enclaves à supprimer

Un "trou" est un polygone d'une classe plus claire entouré d'une classe plus dense.

| Contexte | Taille trou terrain | Action |
|---|---|---|
| Blanc dans vert clair | < 50 m² | Supprimer (absorber dans vert clair) |
| Blanc dans vert moyen | < 30 m² | Supprimer |
| Vert clair dans vert foncé | < 30 m² | Supprimer |

**Exemple :**
```
vert1 (15 m²) / blanc (6 m²) / vert1 (12 m²)
→ vert1 unique (blanc absorbé car < seuil)
```

---

## 3. Corridors — largeur minimale lisible

Un corridor est une zone longue et étroite.

| Type | Largeur mini terrain | Comportement si < seuil |
|---|---|---|
| Couloir blanc dans forêt | 10 m | Absorber dans classe adjacente |
| Bande de vert foncé | 5 m | Absorber |
| Toute bande de végétation | 5 m | Absorber si longueur < 20 m |

---

## 4. Fusion d'îlots proches (distance de fusion)

Deux polygones de même classe séparés par une distance inférieure au seuil → fusionner.

| Classe | Distance fusion terrain |
|---|---|
| Vert foncé (408–410) | 5 m |
| Vert moyen (406–407) | 8 m |
| Jaune (402–403) | 10 m |

> La distance de fusion simule l'"agrandissement symbolique" IOF.

---

## 5. Agrandissement symbolique

Certains objets doivent être **élargis** pour rester lisibles à l'échelle :

- Bande de vert foncé de 2–3 m réelle → élargir à 5 m sur carte
- Ce principe s'applique **après** suppression des petits objets, pas avant

---

## 6. Simplification de contours

| Paramètre | Valeur | Note |
|---|---|---|
| Tolérance Douglas-Peucker | 1.5–2 m terrain | Ne pas aller au-delà |
| Passes Chaikin | 1 | Suffit pour l'arrondi naturel |
| Lissage Bézier/spline | Non recommandé | Gain marginal, complexité élevée |

---

## 7. Hystérésis (éviter l'alternance rapide de classes)

Problème : après seuillage, on peut obtenir vert1/vert2/vert1/vert2 sur quelques mètres.

Solution : zone tampon de transition — un pixel ne peut changer de classe que si la densité dépasse **seuil + δ** (hystérésis).

```
seuil vert1 → vert2 : densité > 0.45
seuil retour vert2 → vert1 : densité < 0.35
δ = 0.10 (marge d'hystérésis)
```

---

## 8. Ordre d'application dans le CO Generalization Engine

**Ordre verrouillé — ne pas modifier sans justification mesurée.**

```
0. Polygonize (GDAL)
1. Dissolve par classe          ← critique : fait AVANT toute suppression
2. Suppression petits trous     ← AVANT les petits polygones (trous nets après dissolve)
3. Suppression petits polygones
4. Fusion îlots proches         ← avant close_corridors (voir note)
5. Fermeture corridors trop étroits  ← APRÈS fusion, pas avant
6. Simplification Douglas-Peucker
7. Lissage Chaikin ×1           ← jamais plus d'une passe
```

**Pourquoi cet ordre :**
- Dissolve en premier : les trous et corridors n'existent qu'après dissolve — opérer avant crée des faux positifs.
- Trous avant petits polygones : un polygone extérieur adjacent à un trou pourrait être faussement éliminé si on supprime les petits d'abord.
- **Fusion AVANT close_corridors** (découverte expérimentale 2026-06-24) : les filaments étroits n'existent pas dans les polygones issus de Polygonize — ils sont créés par le débuffer de la fusion (buffer+dissolve+débuffer). Appliquer close_corridors avant la fusion supprime 0 polygone. La position correcte est après la fusion.
- Simplifier après fusion : agrandir/fusionner avant DP préserve les contours utiles.

**Contrainte d'implémentation (no-hardcode) :**

Le moteur ne doit jamais contenir de valeurs numériques littérales liées à une classe :

```python
# INTERDIT
if class_id == 406:
    min_area = 50

# OBLIGATOIRE
rules = config["generalization"]["min_area_m2"][str(class_id)]
```

Raison : les seuils varient par terrain (Normandie ≠ Landes ≠ Bretagne). Le moteur doit être stable ; les paramètres sont jetables.

**Note backlog — simplification adaptative (pas MVP) :**

La médiane de sommets HAG Grimbosq est 26. Beaucoup de polygones sont déjà simples.
Une simplification adaptative éviterait de dégrader des objets propres :
```
vertices < 30  → pas de DP
vertices < 100 → DP tolérance 1 m
vertices ≥ 100 → DP tolérance 2 m
```
À évaluer après mesure sur corpus FFCO (nombre de sommets carte réelle vs HAG).

---

## 9. Exemples réels (à enrichir)

Structure à compléter avec des cartes FFCO réelles :

| Situation avant | Décision cartographe | Règle déduite |
|---|---|---|
| vert / blanc 2m / vert | vert unique | corridor blanc < Xm → suppression |
| 15 petits verts dispersés | 1 polygone | distance fusion < Ym → dissolve |
| vert foncé 3m × 3m | supprimé | aire < Zm² → suppression |
| *à compléter sur corpus réel* | | |

---

## 10. Ce que ce document ne couvre pas encore

- Interaction végétation / relief (courbes de niveau en zone dense)
- Règles de déplacement (deux symboles qui se chevauchent)
- Priorités entre couches (végétation vs. anthropique)
- Toutes les valeurs numériques (à mesurer sur corpus, pas supposées)

---

## Sources

- ISOM 2017-2 officiel (IOF) — §12 Vegetation, §1 General principles
- Paramètres OCAD : Remove Small Objects, Simplify Objects, Smooth, Generalize
- Corpus cartes FFCO + LiDAR IGN (à constituer)
