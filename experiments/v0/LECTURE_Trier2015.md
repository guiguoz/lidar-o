# Lecture critique — Trier 2015

**Référence** : Trier, Ø.D. (2015). Automatic mapping of forest density from
airborne lidar data. *Geodesy and Cartography*, 41(2): 49–65.
DOI: 10.3846/20296991.2015.1051342

---

## 1. Construction du terrain (§1.3, p.51)

**Citation exacte** :
> "Only the points labelled as 'ground' were included. The ENVI® routines
> TRIANGULATE and CONTOUR were used to generate vector contour lines.
> TRIGRID was used to produce a digital terrain model (DTM) of the 'ground' points."

**Points vérifiés** :
- Classes LAS utilisées : class 2 uniquement (labellisé 'ground')
- Méthode : ENVI TRIGRID = TIN (Triangulated Irregular Network)
- Résolution DTM : implicitement 0.5 m (même résolution que les rasters produits)
- Gestion des trous : non spécifiée dans l'article
- Bords : non spécifiés

**Implémentation lidar-o** : min par cellule + NN fill [TRIER-DEV-DTM]
→ Approximation de TIN. Négligeable à ~10 impl/m² (rares cellules vides).

---

## 2. Définition des "vegetation hits" V (§1.1, §2)

**Citation §1.1** :
> "The data was delivered as LAS files (ASPRS 2010), with each (x, y, z) point
> labelled as 'ground' or 'other'. Each (x, y, z) point also has an intensity
> value, and a return number (1, 2, 3 or 4)."

**Citation §2** :
> "Here, V and G are the number of vegetation and ground hits, respectively,
> within a small neighbourhood around each location, and for V, within a
> height interval."

> "The NDVD of the 0.0–2.0 m above ground vegetation returns contains some
> artefacts in the form of clearly visible stripes (Fig. 4), related to overlaps
> of data from different flight strips. These artefacts were reduced by using
> the returns from 0.2–2.0 m above ground."

**Points établis** :
- Données Trier = **2 classes uniquement** : 'ground' (class 2) et 'other' (class != 2)
- V = retours labellisés 'other' dans HAG ∈ [0.2, 2.0 m]
- G = retours labellisés 'ground' (class 2)
- ReturnNumber : **non filtré pour le calcul NDVD** — tous les retours comptés
  (ReturnNumber 1, 2, 3, 4 tous inclus dans V et G)
- Bande inférieure : 0.2 m (non 0.0 m) pour supprimer artefacts de chevauchement

**Ambiguïté pour Grimbosq** : [TRIER-DEV-V-UNRESOLVED]
Les données Grimbosq contiennent des classes supplémentaires (6=bâtiment, 9=eau,
7=bruit bas) absentes du jeu de données Trier. La publication ne permet pas de
déterminer comment traiter ces classes car elles n'existent pas dans ses données.
→ Convention : V = tous retours non-class2 dans HAG [0.2, 2.0 m).

---

## 3. NDVD — formule (§2, Eq.1)

NDVD = (V − G) / (V + G)

Plage : [-1, 1]
- +1 = 100% végétation, 0% sol
- -1 = 0% végétation, 100% sol
- NaN si V + G = 0 (cellule sans aucun retour)

---

## 4. Noyau de voisinage (§2, Fig.3)

**Citation** :
> "Based on trial and error, we use a circular neighbourhood with radius = 2.0 m,
> giving equal weight to all hits within a 1.0 m radius from the centre, and
> linearly decreasing weight from 1.0 m to 2.0 m from the centre (Fig. 3)."

- Rayon interne : 1.0 m (poids = 1.0)
- Rayon externe : 2.0 m (poids = 0.0)
- Forme : plat-conique (chapeau tronqué)
- Résolution : 0.5 m/px → noyau 9×9 pixels

---

## 5. Résolution et agrégation (§2, §2.2)

**Citation §2** :
> "With two emitted pulses per m², 0.5 m pixel size was considered adequate."

**Citation §2.2** :
> "Aggregate the NDVD of the 0.2 m to 2.0 m vegetation height, to 1.0 m resolution"

- NDVD calculé à 0.5 m
- Agrégation à 1.0 m avant seuillage

---

## 6. Seuils NDVD (§2.2, Table 5)

| Classe      | Vitesse réduite | 2 impl/m² | 10 impl/m² |
|-------------|-----------------|-----------|------------|
| Slow run    | 20–50%          | -0.20     | 0.00       |
| Walk        | 50–80%          | 0.20      | 0.35       |
| Fight       | 80–100%         | 0.60      | 0.70       |

Mapping ISOM :
- slow run → 406 (vert clair)
- walk → 408 (vert moyen)
- fight → 410 (vert foncé)

---

## 7. Généralisation morphologique (§2.2)

**Citation** :
> "Use binary morphological closing with a 7×7 disk kernel"
> "Use binary morphological opening with a 3×3 disk kernel"
> "Use binary morphological closing with a 9×9 disk kernel"
> "Use binary morphological opening with a 5×5 disk kernel"
> "Use binary morphological closing with a 11×11 disk kernel"
> "Use binary morphological opening with a 7×7 disk kernel"
> "Remove the 'open areas mask'"
> "Remove small patches and thin strips of dense vegetation by using binary
>  morphological opening with a 3×3 pixels square kernel"
> "Remove dense vegetation objects smaller than the smallest allowed area.
>  For 'slow run' and 'walk', this is 225 m², and for 'fight', this is 112.5 m²."

Séquence exacte (à 1.0 m de résolution) :
1. close disk  7×7
2. open  disk  3×3
3. close disk  9×9
4. open  disk  5×5
5. close disk  11×11
6. open  disk  7×7
7. retrait masque zones ouvertes
8. open  carré 3×3
9. filtre aire minimale

---

## 8. Masque zones ouvertes (§2.1)

Le masque est obtenu par :
- agrégation de l'image de hauteur de végétation (nDSM) à 1.0 m
- seuil à 0.75 m (végétation < 0.75 m = zone ouverte)
- séquence morphologique complète (§2.1) — **non reproduite fidèlement**
  [TRIER-DEV-OPENMAP]
- aire minimale 22.5 m² (Fig.6k, pour le masque utilisé par §2.2)

---

## 9. Densité des données Trier

| Paramètre | 2 impl/m² | 10 impl/m² |
|-----------|-----------|------------|
| Altitude de vol | 2000 m | 250–450 m |
| Taux de répétition laser | 117 900 Hz | 150 000 Hz |
| Zones couvertes | tout Oslo | forêts d'Oslo |

Grimbosq = ~15 impl/m² → hors domaine documenté.
Run principal : sous-échantillonnage à ~10 impl/m² par impulsion (GpsTime).

---

## 10. Points non traités / absents de l'article

- Gestion des cellules sans retour pour NDVD : non spécifiée (→ NaN)
- Résolution exacte du DTM : non spécifiée (→ 0.5 m supposé)
- Gestion des trous dans le DTM : non spécifiée (→ NN fill)
- Classes LAS non-ground au-delà de 'other' : non concernées (données à 2 classes)
- Traitement des artefacts autres que les chevauchements de bandes : non spécifié
- Méthode d'agrégation 0.5 m → 1 m : non spécifiée (→ moyenne)
