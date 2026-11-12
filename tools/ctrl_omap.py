"""Validation structurelle d'un fichier .omap (OpenOrienteering Mapper).

Ne compte que les objets de carte dans le bloc <objects>, jamais les <object>
graphiques inclus dans les définitions de symboles (<symbol> → <element> → <object>).

Usage CLI :
    python tools/ctrl_omap.py <file.omap> [<isom_template.omap>]

Importable :
    from tools.ctrl_omap import count_objects, OmapCounts, load_code_to_id
"""
from __future__ import annotations

import sys
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path

_NS = "http://openorienteering.org/apps/mapper/xml/v2"
_NSB = f"{{{_NS}}}"


@dataclass(frozen=True)
class OmapCounts:
    """Résultat du comptage des objets de carte d'un .omap."""
    counts: dict[str, int]      # {"406": 1340, "408": 409, ...}
    unknown_sym: list[str]      # IDs de symboles non reconnus (format "sym_<id>")
    declared: int               # attribut count= sur <objects>
    actual: int                 # nombre réel d'enfants <object> dans <objects>
    count_match: bool           # declared == actual


def load_code_to_id(isom_path: Path) -> dict[int, int]:
    """Charge le mapping code ISOM → id interne depuis un fichier .omap gabarit.

    Exclut les variantes décimales (406.1, 406.2…) : seuls les codes entiers
    correspondent aux symboles de base ISOM.
    """
    source = isom_path.read_text(encoding="utf-8")
    root = ET.fromstring(source)
    code_to_id: dict[int, int] = {}
    for sym in root.iter(f"{_NSB}symbol"):
        raw_code = sym.get("code")
        raw_id = sym.get("id")
        if raw_code and raw_id and "." not in raw_code:
            try:
                code_to_id[int(raw_code)] = int(raw_id)
            except ValueError:
                pass
    return code_to_id


def count_objects(
    omap_path: Path,
    code_to_id: dict[int, int] | None = None,
) -> OmapCounts:
    """Compte les objets de carte dans le bloc <objects> d'un .omap.

    Parcourt uniquement les enfants directs du premier <objects> de la carte.
    Les <object> à l'intérieur des définitions de symboles (parents <element>)
    ne sont pas des objets de carte et sont ignorés.

    code_to_id : mapping code ISOM → id interne (optionnel).
      - Fourni : les objets sont comptés par code ISOM ("406", "408", …).
      - Absent  : les objets sont comptés par id de symbole brut ("id_86", …).
    Les objets dont le symbole n'est pas dans code_to_id sont listés dans
    unknown_sym (format "sym_<id>").
    """
    tree = ET.parse(str(omap_path))
    root = tree.getroot()

    use_mapping = code_to_id is not None
    id_to_code: dict[str, str] = (
        {str(v): str(k) for k, v in code_to_id.items()} if use_mapping else {}
    )

    objects_elem = root.find(f".//{_NSB}objects")
    if objects_elem is None:
        return OmapCounts(counts={}, unknown_sym=[], declared=0, actual=0, count_match=True)

    declared = int(objects_elem.get("count", 0))
    counts: dict[str, int] = {}
    unknown_sym: list[str] = []
    actual = 0

    for child in objects_elem:
        if child.tag != f"{_NSB}object":
            continue
        actual += 1
        sym_id = child.get("symbol")
        if sym_id is None:
            label = "sym_none"
            unknown_sym.append(label)
        elif use_mapping:
            code = id_to_code.get(sym_id)
            if code is None:
                label = f"sym_{sym_id}"
                unknown_sym.append(label)
            else:
                label = code
        else:
            label = f"id_{sym_id}"
        counts[label] = counts.get(label, 0) + 1

    return OmapCounts(
        counts=counts,
        unknown_sym=sorted(set(unknown_sym)),
        declared=declared,
        actual=actual,
        count_match=(declared == actual),
    )


def validate_omap(
    omap_path: Path,
    isom_path: Path | None = None,
) -> dict:
    """Rapport structurel complet d'un .omap.

    Retourne un dict avec :
      - xml_valid (bool)
      - counts (OmapCounts)
      - isom_path_used (str | None)
    """
    result: dict = {"xml_valid": False, "counts": None, "isom_path_used": None}
    try:
        ET.parse(str(omap_path))
        result["xml_valid"] = True
    except ET.ParseError as exc:
        result["xml_error"] = str(exc)
        return result

    code_to_id: dict[int, int] | None = None
    if isom_path and isom_path.exists():
        code_to_id = load_code_to_id(isom_path)
        result["isom_path_used"] = str(isom_path)

    result["counts"] = count_objects(omap_path, code_to_id)
    return result


# ── CLI ───────────────────────────────────────────────────────────────────────

def _main() -> None:
    if len(sys.argv) < 2:
        print(f"Usage: python {sys.argv[0]} <file.omap> [<isom_template.omap>]")
        sys.exit(1)

    omap_path = Path(sys.argv[1])
    isom_path = Path(sys.argv[2]) if len(sys.argv) > 2 else None

    if not omap_path.exists():
        print(f"Erreur : {omap_path} introuvable")
        sys.exit(1)

    report = validate_omap(omap_path, isom_path)

    print(f"Fichier  : {omap_path}")
    print(f"XML valide : {report['xml_valid']}")
    if not report["xml_valid"]:
        print(f"Erreur XML : {report.get('xml_error')}")
        return

    c: OmapCounts = report["counts"]
    print(f"Gabarit ISOM : {report['isom_path_used'] or '(non fourni — IDs bruts)'}")
    print(f"Objets de carte déclarés : {c.declared}")
    print(f"Objets de carte effectifs : {c.actual}")
    print(f"Cohérence count : {'OK' if c.count_match else 'ERREUR'}")
    print(f"Comptes par ISOM : {c.counts}")
    if c.unknown_sym:
        print(f"Symboles inconnus ({len(c.unknown_sym)}) : {c.unknown_sym[:10]}")
    else:
        print("Symboles inconnus : aucun")


if __name__ == "__main__":
    _main()
