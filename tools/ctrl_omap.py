"""Contrôle reproductible des objets d'un fichier .omap (verdicts V4).

Compte UNIQUEMENT les objets du bloc de carte ``<objects>``. Les nœuds
``<object>`` imbriqués dans les définitions de palette / symboles
(``<symbols>/<symbol>/<element>/<object>``) ne sont jamais comptés :
c'est la régression du bug ``sym_?`` (compteur qui parcourait tout le
document via ``root.iter()`` et prenait les sous-éléments graphiques des
symboles pour des objets de carte).

Le mapping id interne → code ISOM est lu par défaut dans le bloc
``<symbols>`` du fichier lui-même (attributs ``code`` / ``id``, codes
entiers uniquement — les variantes décimales du type "406.1" sont
exclues, même règle que ``src.omap_writer.load_template``). Un second
argument CLI permet d'imposer une autre source de mapping.

Sémantique du mapping (consigne V4.0, 2026-10-03) :
``id_to_code is None``  → mapping non fourni (``by_code = None``) ;
``id_to_code == {}``    → mapping fourni mais vide (``by_code`` vide,
tous les ids signalés en ``unknown_symbol_ids``).

CLI : ``python tools/ctrl_omap.py <fichier.omap> [<mapping.omap>]``
Sortie : rapport texte ; code retour 0 si cohérent, 1 sinon
(attribut ``count`` incohérent, objet sans attribut ``symbol``,
symbole inconnu quand un mapping est fourni).
"""
from __future__ import annotations

import argparse
import sys
import xml.etree.ElementTree as ET
from collections import Counter
from pathlib import Path


def _local(tag: str) -> str:
    """Nom local d'une balise, namespace éventuel retiré."""
    return tag.rsplit("}", 1)[-1]


def load_id_to_code(path: str | Path) -> dict[int, int]:
    """Extrait du bloc <symbols> le mapping id interne → code ISOM.

    Règle identique à ``src.omap_writer.load_template`` : attributs
    ``code`` et ``id`` présents, code sans point décimal (les variantes
    "406.1" ne sont pas des symboles de base).
    """
    root = ET.fromstring(Path(path).read_text(encoding="utf-8"))
    id_to_code: dict[int, int] = {}
    for node in root.iter():
        if _local(node.tag) != "symbol":
            continue
        raw_code, raw_id = node.get("code"), node.get("id")
        if raw_code is None or raw_id is None or "." in raw_code:
            continue
        try:
            id_to_code[int(raw_id)] = int(raw_code)
        except ValueError:
            pass
    return id_to_code


def _objects_block(root: ET.Element) -> ET.Element:
    """Le bloc de carte <objects> — fils directs de la racine uniquement."""
    blocks = [c for c in root if _local(c.tag) == "objects"]
    if len(blocks) != 1:
        raise ValueError(
            f"Bloc <objects> attendu exactement une fois en racine, "
            f"trouvé {len(blocks)}"
        )
    return blocks[0]


def count_map_objects(
    path: str | Path,
    id_to_code: dict[int, int] | None = None,
) -> dict:
    """Compte les objets de carte d'un .omap, hors définitions de symboles.

    Retourne un dict :
      ``n_map_objects``       nombre d'<object> du bloc de carte ;
      ``count_attr``          attribut ``count`` du bloc (int ou None) ;
      ``count_attr_ok``       True ssi attribut présent et == n_map_objects ;
      ``by_symbol_id``        Counter des attributs ``symbol`` (bruts) ;
      ``missing_symbol_attr`` nombre d'objets sans attribut ``symbol`` ;
      ``by_code``             Counter par code ISOM, ou None si mapping
                              non fourni (distinction None / {}) ;
      ``unknown_symbol_ids``  Counter des ids sans code connu, ou None.
    """
    root = ET.fromstring(Path(path).read_text(encoding="utf-8"))
    block = _objects_block(root)
    objs = [c for c in block if _local(c.tag) == "object"]

    count_attr_raw = block.get("count")
    count_attr = int(count_attr_raw) if count_attr_raw is not None else None

    res: dict = {
        "path": str(path),
        "n_map_objects": len(objs),
        "count_attr": count_attr,
        "count_attr_ok": count_attr is not None and count_attr == len(objs),
        "by_symbol_id": Counter(o.get("symbol") for o in objs),
        "missing_symbol_attr": sum(1 for o in objs if o.get("symbol") is None),
    }

    if id_to_code is None:
        res["by_code"] = None
        res["unknown_symbol_ids"] = None
    else:
        by_code: Counter = Counter()
        unknown: Counter = Counter()
        for o in objs:
            sid = o.get("symbol")
            if sid is None:
                continue
            try:
                key = int(sid)
            except ValueError:
                unknown[sid] += 1
                continue
            code = id_to_code.get(key)
            if code is None:
                unknown[sid] += 1
            else:
                by_code[code] += 1
        res["by_code"] = by_code
        res["unknown_symbol_ids"] = unknown
    return res


def _format_report(res: dict) -> str:
    lines = [
        f"fichier           : {res['path']}",
        f"objets de carte   : {res['n_map_objects']} "
        f"(attribut count : {res['count_attr']}, "
        f"{'ok' if res['count_attr_ok'] else 'INCOHÉRENT'})",
        f"sans attr symbol  : {res['missing_symbol_attr']}",
    ]
    if res["by_code"] is None:
        lines.append("par code ISOM     : (mapping non fourni)")
        lines.append(f"par id symbole    : {dict(res['by_symbol_id'])}")
    else:
        codes = " ".join(f"{c}={n}" for c, n in sorted(res["by_code"].items()))
        lines.append(f"par code ISOM     : {codes or '(vide)'}")
        unk = res["unknown_symbol_ids"]
        lines.append(f"ids sans code     : {dict(unk) if unk else 'aucun'}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("fichier", help="fichier .omap à contrôler")
    ap.add_argument(
        "mapping",
        nargs="?",
        default=None,
        help="source du mapping id → code ISOM (défaut : le fichier lui-même)",
    )
    args = ap.parse_args(argv)

    mapping_src = args.mapping or args.fichier
    id_to_code = load_id_to_code(mapping_src)
    res = count_map_objects(args.fichier, id_to_code)
    print(_format_report(res))

    problemes: list[str] = []
    if not res["count_attr_ok"]:
        problemes.append("attribut count incohérent avec le bloc <objects>")
    if res["missing_symbol_attr"]:
        problemes.append(f"{res['missing_symbol_attr']} objet(s) sans attribut symbol")
    if res["unknown_symbol_ids"]:
        problemes.append(f"symboles inconnus : {dict(res['unknown_symbol_ids'])}")
    if problemes:
        print("PROBLÈMES : " + " ; ".join(problemes))
        return 1
    print("OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
