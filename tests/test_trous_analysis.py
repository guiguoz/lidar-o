"""Tests synthétiques pour scripts/trous_analysis.py.

Chaque test construit un masque et un shade array artificiel pour vérifier
le comportement exact des fonctions d'analyse des zones ouvertes.
"""
import numpy as np
import pytest

import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))

from scripts.trous_analysis import (
    KP_BLANC,
    KP_JAUNE,
    KP_FIRST_GREEN,
    build_trapeze_mask,
    mask_boundary,
    get_interior_trous,
    cc_correspondences,
    classify_open_zones,
    overlap_label,
    TRAPEZE_VERTICES,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def solid_mask(shape):
    """Masque entièrement True sauf la bordure extérieure."""
    m = np.ones(shape, dtype=bool)
    m[0, :] = m[-1, :] = m[:, 0] = m[:, -1] = False
    return m


def shade_all(shape, val):
    return np.full(shape, val, dtype=np.uint8)


# ---------------------------------------------------------------------------
# 1. Zone claire touchant une limite oblique du masque
# ---------------------------------------------------------------------------

class TestBoundaryOblique:
    """Masque triangulaire (frontière oblique) : un blanc au bord oblique
    doit être classé 'bord', pas 'intérieur'."""

    def _oblique_mask(self, n=15):
        """Masque : pixels avec col > row (triangle inférieur droit)."""
        m = np.zeros((n, n), dtype=bool)
        for r in range(n):
            m[r, r + 1:] = True
        return m

    def test_blanc_adjacent_oblique_boundary_is_border(self):
        n = 15
        mask = self._oblique_mask(n)
        shade = shade_all((n, n), 3)  # tout en vert (shade 3)
        shade[5, 6] = KP_BLANC        # pixel blanc au bord oblique
        # (5,6) est dans le masque (col=6 > row=5), adjacent à (5,5) hors masque
        labeled, interior_ids = get_interior_trous(shade, mask)
        assert len(interior_ids) == 0, (
            "pixel blanc adjacent à la frontière oblique ne doit pas être intérieur"
        )

    def test_blanc_deep_inside_oblique_mask_is_interior(self):
        n = 20
        mask = self._oblique_mask(n)
        shade = shade_all((n, n), 3)
        # Pixel blanc profondément intérieur : (2, 18) — entouré de masque
        shade[2, 18] = KP_BLANC
        labeled, interior_ids = get_interior_trous(shade, mask)
        assert len(interior_ids) == 1, (
            "pixel blanc profondément intérieur doit être dans interior_ids"
        )


# ---------------------------------------------------------------------------
# 2. Zone claire réellement enclavée
# ---------------------------------------------------------------------------

class TestEnclosedTrou:
    def test_single_enclosed_blanc(self):
        mask = solid_mask((10, 10))
        shade = shade_all((10, 10), 3)
        shade[5, 5] = KP_BLANC
        labeled, interior_ids = get_interior_trous(shade, mask)
        assert len(interior_ids) == 1

    def test_multiple_enclosed_blobs(self):
        mask = solid_mask((15, 15))
        shade = shade_all((15, 15), 3)
        shade[3, 3] = KP_BLANC
        shade[10, 10] = KP_BLANC
        labeled, interior_ids = get_interior_trous(shade, mask)
        assert len(interior_ids) == 2

    def test_jaune_enclosed(self):
        mask = solid_mask((10, 10))
        shade = shade_all((10, 10), 3)
        shade[4, 4] = KP_JAUNE
        labeled, interior_ids = get_interior_trous(shade, mask)
        assert len(interior_ids) == 1

    def test_blanc_at_mask_edge_excluded(self):
        mask = solid_mask((10, 10))
        shade = shade_all((10, 10), 3)
        shade[1, 5] = KP_BLANC  # adjacent à mask[0,:] = False
        labeled, interior_ids = get_interior_trous(shade, mask)
        assert len(interior_ids) == 0


# ---------------------------------------------------------------------------
# 3. Deux zones B fusionnées dans D
# ---------------------------------------------------------------------------

class TestMergeBD:
    """Deux CC distinctes dans from fusionnent en une seule dans to."""

    _STI = {2: 0, 3: 406, 4: 406, 5: 408, 6: 408, 7: 410, 8: 410}

    def _setup(self):
        mask = solid_mask((20, 20))
        from_s = shade_all((20, 20), 4)   # tout 406
        to_s   = shade_all((20, 20), 4)   # tout 406

        # Deux CC dans from séparées par un blanc
        from_s[5, 3:7]   = KP_BLANC       # blanc séparateur
        from_s[5, 3:5]   = 4               # force les deux blocs à être connectés par la zone blanc
        # Séparateur : pixels blancs entre les deux blocs 406
        from_s[5, 5:7]   = KP_BLANC

        # Dans to : le blanc est comblé → une seule CC 406
        # (to_s est déjà tout 406)
        return mask, from_s, to_s

    def test_merge_detected(self):
        mask = solid_mask((15, 15))
        sti = self._STI
        # from : deux îlots 406 séparés par du blanc
        from_s = shade_all((15, 15), KP_BLANC)
        mask_inner = np.zeros((15, 15), dtype=bool)
        mask_inner[2:12, 2:12] = True
        from_s[3:6, 3:6]  = 4  # CC 406 #1
        from_s[7:10, 7:10] = 4  # CC 406 #2
        # to : les deux fusionnés
        to_s = shade_all((15, 15), KP_BLANC)
        to_s[3:10, 3:10] = 4  # une seule grande CC 406
        mask_use = solid_mask((15, 15))
        events, summary = cc_correspondences(from_s, to_s, mask_use, 406, sti)
        assert summary["merge"]["n"] >= 1, f"Aucune fusion détectée: {summary}"


# ---------------------------------------------------------------------------
# 4. Zone partiellement conservée
# ---------------------------------------------------------------------------

class TestPartialConservation:
    _STI = {2: 0, 3: 406, 4: 406, 5: 408, 6: 408, 7: 410, 8: 410}

    def test_partial_pct(self):
        mask = solid_mask((20, 20))
        sti = self._STI
        from_s = shade_all((20, 20), KP_BLANC)
        to_s   = shade_all((20, 20), KP_BLANC)
        # Une CC 406 de 16 px dans from
        from_s[5:9, 5:9] = 4  # 4×4 = 16 px
        # Dans to : seulement la moitié gauche (4×2 = 8 px = 50%)
        to_s[5:9, 5:7]   = 4
        events, summary = cc_correspondences(from_s, to_s, mask, 406, sti)
        persist_events = [e for e in events if e.event_type == "persist"]
        assert len(persist_events) == 1
        assert 40 <= persist_events[0].pct_overlap <= 60, (
            f"Attendu ~50%, obtenu {persist_events[0].pct_overlap}"
        )

    def test_overlap_label_categories(self):
        assert "persistante"         in overlap_label(95)
        assert "partiellement conservee" in overlap_label(70)
        assert "partiellement disparue"  in overlap_label(30)
        assert "quasi-disparue"      in overlap_label(5)


# ---------------------------------------------------------------------------
# 5. Shade 2 selon les deux définitions
# ---------------------------------------------------------------------------

class TestShade2Classification:
    """Shade 2 (KP_FIRST_GREEN) doit être ISOM 0 (vert0), pas une clairière."""

    _STI_CORRECT  = {2: 0, 3: 406, 4: 406, 5: 408, 6: 408, 7: 410, 8: 410}
    _STI_INCORRECT = {2: 406, 3: 406, 4: 406, 5: 408, 6: 408, 7: 410, 8: 410}

    def test_shade2_is_vert0_not_clairiere(self):
        mask = solid_mask((10, 10))
        shade = shade_all((10, 10), 3)
        shade[5, 5] = KP_FIRST_GREEN  # shade 2

        # Avec le mapping correct : shade 2 → ISOM 0 (vert0)
        stats_ok = classify_open_zones(shade, mask, self._STI_CORRECT)
        # shade 2 n'est PAS une zone ouverte (blanc/jaune) → aucune enclave blanc/jaune
        assert stats_ok.blanc_enclave_n == 0
        assert stats_ok.jaune_enclave_n == 0
        assert stats_ok.vert0_ha > 0

    def test_shade2_not_counted_as_406_in_correct_mapping(self):
        mask = solid_mask((10, 10))
        shade = shade_all((10, 10), KP_BLANC)
        shade[5, 5] = KP_FIRST_GREEN  # shade 2

        stats_correct   = classify_open_zones(shade, mask, self._STI_CORRECT)
        stats_incorrect = classify_open_zones(shade, mask, self._STI_INCORRECT)
        # Avec le mapping correct : shade 2 va dans vert0, pas 406
        assert stats_correct.vert0_ha > 0
        assert stats_correct.ha_406 == 0.0
        # Avec le mapping incorrect : shade 2 irait dans 406
        assert stats_incorrect.ha_406 > 0
        assert stats_incorrect.vert0_ha == 0.0


# ---------------------------------------------------------------------------
# 6. Trapèze : vérification du polygone
# ---------------------------------------------------------------------------

class TestTrapezeMask:
    def test_shape(self):
        m = build_trapeze_mask((340, 370), TRAPEZE_VERTICES)
        assert m.shape == (340, 370)
        assert m.dtype == bool

    def test_reasonable_area(self):
        m = build_trapeze_mask((340, 370), TRAPEZE_VERTICES)
        ha = m.sum() / 10000.0
        # Le bois trapézoïdal doit faire entre 3 et 6 ha
        assert 3.0 <= ha <= 6.0, f"Surface trapèze inattendue : {ha:.2f} ha"

    def test_vertices_inside(self):
        m = build_trapeze_mask((340, 370), TRAPEZE_VERTICES)
        # Les centroïdes intérieurs doivent être dans le masque
        centroid_row = int(np.mean([v[0] for v in TRAPEZE_VERTICES]))
        centroid_col = int(np.mean([v[1] for v in TRAPEZE_VERTICES]))
        assert m[centroid_row, centroid_col], (
            f"Centroïde ({centroid_row},{centroid_col}) pas dans le masque"
        )

    def test_sud_excluded(self):
        m = build_trapeze_mask((340, 370), TRAPEZE_VERTICES)
        assert m[250, 200] == False, "row 250 devrait être exclu (jardins sud)"

    def test_jardin_est_excluded(self):
        m = build_trapeze_mask((340, 370), TRAPEZE_VERTICES)
        assert m[25, 340] == False, "jardin est (row=25, col=340) devrait être exclu"


# ---------------------------------------------------------------------------
# 7. mask_boundary sur masque irrégulier
# ---------------------------------------------------------------------------

class TestMaskBoundary:
    def test_all_pixels_rectangular(self):
        # Masque tout-vrai : pas d'extérieur → frontière vide
        mask = np.ones((5, 5), dtype=bool)
        bound = mask_boundary(mask)
        assert bound.sum() == 0, "Masque sans extérieur : frontière doit être vide"

    def test_partial_mask_perimeter(self):
        # Sous-masque 3×3 au centre d'un array 7×7
        mask = np.zeros((7, 7), dtype=bool)
        mask[2:5, 2:5] = True
        bound = mask_boundary(mask)
        # Le périmètre du carré 3×3 = 8 pixels
        assert bound.sum() == 8, f"Périmètre 3×3 attendu 8, obtenu {bound.sum()}"

    def test_interior_not_boundary(self):
        mask = np.ones((7, 7), dtype=bool)
        bound = mask_boundary(mask)
        assert not bound[3, 3], "Pixel central ne devrait pas être frontière"

    def test_irregular_mask_boundary(self):
        mask = np.zeros((10, 10), dtype=bool)
        mask[3:7, 3:7] = True  # carré intérieur
        bound = mask_boundary(mask)
        # Les bords du carré sont frontière
        assert bound[3, 3]
        assert bound[6, 6]
        # Le centre du carré n'est pas frontière
        assert not bound[5, 5]
