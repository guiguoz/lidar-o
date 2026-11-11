"""Métriques d'évaluation multiclasse.

Convention :
  - Pixels prédits LABEL_NODATA (inconnus) sur une référence évaluable = pénalisés.
  - Macro-IoU : classes absentes dans la référence = IoU 0.0 (comptées, pas ignorées).
  - IoU de présence végétation : catégories veg_406/408/410 regroupées.
"""
from __future__ import annotations

import numpy as np
from dataclasses import dataclass, field

from config import CLASS_NAMES, CLASS_CODES, N_CLASSES, LABEL_NODATA


@dataclass
class ClassMetrics:
    name: str
    n_ref: int     # pixels dans la référence
    tp: int
    fp: int
    fn: int
    iou: float
    precision: float
    recall: float


@dataclass
class EvalResult:
    split_name: str
    n_known: int      # pixels avec label évaluable (non NODATA)
    n_pred_nodata: int  # prédictions NODATA sur référence évaluable
    per_class: list[ClassMetrics]
    macro_iou: float    # moyenne IoU sur toutes les classes (absentes = 0)
    iou_presence: float # IoU végétation regroupée
    precision_presence: float
    recall_presence: float
    conf_matrix: np.ndarray  # (N_CLASSES+1, N_CLASSES+1) — dernière ligne/col = nodata

    # Scores
    @property
    def score(self) -> float:
        """Critère de sélection principal : macro-IoU."""
        return self.macro_iou


def _iou(tp: int, fp: int, fn: int) -> float:
    d = tp + fp + fn
    return float(tp) / d if d > 0 else 0.0


def evaluate(
    pred: np.ndarray,       # (H, W) uint8/uint16 — LABEL_NODATA pour inconnu
    labels: np.ndarray,     # (H, W) uint8
    split_name: str,
    block_mask: np.ndarray | None = None,  # (H, W) bool — restreint à ce bloc
    support_grid: np.ndarray | None = None,
) -> EvalResult:
    """Évalue pred contre labels sur les pixels évaluables.

    Si block_mask fourni, évalue uniquement sur les pixels de ce bloc.
    Pixels évaluables = (labels != LABEL_NODATA) AND (dans bloc si fourni).
    Prédiction LABEL_NODATA sur référence évaluable = FN.
    """
    assert pred.shape == labels.shape

    if block_mask is not None:
        known = (labels != LABEL_NODATA) & block_mask
    else:
        known = (labels != LABEL_NODATA)
    n_known = int(known.sum())
    if n_known == 0:
        # Bloc entièrement inconnu — retourne des métriques nulles
        return EvalResult(
            split_name=split_name,
            n_known=0, n_pred_nodata=0,
            per_class=[], macro_iou=0.0,
            iou_presence=0.0, precision_presence=0.0, recall_presence=0.0,
            conf_matrix=np.zeros((N_CLASSES + 1, N_CLASSES + 1), int),
        )

    pred_flat  = pred[known].astype(np.int32)
    label_flat = labels[known].astype(np.int32)

    pred_nodata = pred_flat == LABEL_NODATA
    n_pred_nodata = int(pred_nodata.sum())

    # Matrice de confusion (N_CLASSES+1) × (N_CLASSES+1) : dernière = nodata
    nc = N_CLASSES + 1
    conf = np.zeros((nc, nc), dtype=np.int64)
    for ref_code in range(N_CLASSES):
        ref_mask = label_flat == ref_code
        for pred_code in range(N_CLASSES):
            conf[ref_code, pred_code] = int(((pred_flat == pred_code) & ref_mask).sum())
        conf[ref_code, N_CLASSES] = int((pred_nodata & ref_mask).sum())

    # IoU par classe
    per_class: list[ClassMetrics] = []
    ious: list[float] = []
    for idx, name in enumerate(CLASS_NAMES):
        ref_mask  = label_flat == idx
        pred_mask = pred_flat == idx
        tp = int((pred_mask & ref_mask).sum())
        fp = int((pred_mask & ~ref_mask).sum())
        # fn inclut les prédictions NODATA sur cette classe
        fn = int((~pred_mask & ref_mask).sum())   # ~pred_mask inclut LABEL_NODATA
        n_ref = int(ref_mask.sum())
        iou   = _iou(tp, fp, fn)
        ious.append(iou)
        per_class.append(ClassMetrics(
            name=name, n_ref=n_ref, tp=tp, fp=fp, fn=fn,
            iou=iou,
            precision=float(tp) / (tp + fp) if (tp + fp) > 0 else 0.0,
            recall=float(tp) / (tp + fn) if (tp + fn) > 0 else 0.0,
        ))

    macro_iou = float(np.mean(ious))  # classes absentes (n_ref=0) → IoU=0

    # IoU de présence végétation (veg_406, veg_408, veg_410 regroupés)
    veg_codes = {CLASS_CODES[n] for n in ("veg_406", "veg_408", "veg_410")}
    ref_veg  = np.isin(label_flat, list(veg_codes))
    pred_veg = np.isin(pred_flat,  list(veg_codes))
    tp_p = int((pred_veg &  ref_veg).sum())
    fp_p = int((pred_veg & ~ref_veg).sum())
    fn_p = int((~pred_veg & ref_veg).sum())   # inclut NODATA prédit sur veg

    return EvalResult(
        split_name=split_name,
        n_known=n_known,
        n_pred_nodata=n_pred_nodata,
        per_class=per_class,
        macro_iou=macro_iou,
        iou_presence=_iou(tp_p, fp_p, fn_p),
        precision_presence=float(tp_p) / (tp_p + fp_p) if (tp_p + fp_p) > 0 else 0.0,
        recall_presence=float(tp_p) / (tp_p + fn_p) if (tp_p + fn_p) > 0 else 0.0,
        conf_matrix=conf.astype(int),
    )


def print_eval(res: EvalResult) -> None:
    print(f"\n-- {res.split_name} --")
    print(f"  Pixels eval : {res.n_known:,}  |  pred NODATA : {res.n_pred_nodata}")
    print(f"  {'Classe':>12}  {'n_ref':>6}  {'IoU':>6}  {'Prec':>6}  {'Rec':>6}")
    for cm in res.per_class:
        flag = "  ← ABSENT" if cm.n_ref == 0 else ""
        print(f"  {cm.name:>12}  {cm.n_ref:>6}  {cm.iou:.4f}  {cm.precision:.4f}  {cm.recall:.4f}{flag}")
    print(f"  {'macro-IoU':>12}  {'':>6}  {res.macro_iou:.4f}")
    print(f"  {'IoU_presence':>12}  {'':>6}  {res.iou_presence:.4f}  "
          f"{res.precision_presence:.4f}  {res.recall_presence:.4f}")


def eval_to_dict(res: EvalResult) -> dict:
    return {
        "split": res.split_name,
        "n_known": res.n_known,
        "n_pred_nodata": res.n_pred_nodata,
        "macro_iou": round(res.macro_iou, 6),
        "iou_presence": round(res.iou_presence, 6),
        "precision_presence": round(res.precision_presence, 6),
        "recall_presence": round(res.recall_presence, 6),
        "per_class": [
            {
                "name": cm.name, "n_ref": cm.n_ref,
                "tp": cm.tp, "fp": cm.fp, "fn": cm.fn,
                "iou": round(cm.iou, 6),
                "precision": round(cm.precision, 6),
                "recall": round(cm.recall, 6),
            }
            for cm in res.per_class
        ],
    }
