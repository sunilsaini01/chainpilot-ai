"""Metrics and calibration for the late-delivery classifier.

Why these metrics: only about 6-13% of orders are late, so plain accuracy is
misleading (always saying "on time" is ~90% accurate). We use:

- PR-AUC (average precision): how well risky orders are ranked above safe ones,
  focused on the rare late class. A random ranking scores the late rate itself.
- ROC-AUC: ranking quality over both classes (0.5 = random).
- Brier score and log loss: how good the probabilities themselves are.
- Expected calibration error (ECE): average gap between predicted probability and
  the observed late rate, over 10 probability bins. 0 = perfectly calibrated.
- Precision / recall / F1 at a decision threshold: what happens when we flag orders.
"""

import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (
    average_precision_score,
    brier_score_loss,
    log_loss,
    precision_recall_curve,
    roc_auc_score,
)

N_BINS = 10
EPSILON = 1e-6  # keeps log-odds finite for scores of exactly 0 or 1


def expected_calibration_error(y: np.ndarray, p: np.ndarray, n_bins: int = N_BINS) -> float:
    """Weighted mean |observed late rate - mean predicted probability| over equal-width bins."""
    bins = np.minimum((p * n_bins).astype(int), n_bins - 1)
    error = 0.0
    for b in range(n_bins):
        in_bin = bins == b
        if in_bin.any():
            error += in_bin.mean() * abs(y[in_bin].mean() - p[in_bin].mean())
    return float(error)


def reliability_table(y: np.ndarray, p: np.ndarray, n_bins: int = N_BINS) -> list[dict]:
    """Per probability bin: orders, mean predicted probability, observed late rate."""
    bins = np.minimum((p * n_bins).astype(int), n_bins - 1)
    rows = []
    for b in range(n_bins):
        in_bin = bins == b
        if in_bin.any():
            rows.append(
                {
                    "bin": f"{b / n_bins:.1f}-{(b + 1) / n_bins:.1f}",
                    "orders": int(in_bin.sum()),
                    "mean_predicted": round(float(p[in_bin].mean()), 4),
                    "observed_late_rate": round(float(y[in_bin].mean()), 4),
                }
            )
    return rows


def threshold_metrics(y: np.ndarray, p: np.ndarray, threshold: float) -> dict[str, float]:
    flagged = p >= threshold
    true_positive = int((flagged & (y == 1)).sum())
    precision = true_positive / flagged.sum() if flagged.any() else 0.0
    recall = true_positive / (y == 1).sum() if (y == 1).any() else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return {
        "threshold": round(float(threshold), 4),
        "flagged_share": round(float(flagged.mean()), 4),
        "precision": round(float(precision), 4),
        "recall": round(float(recall), 4),
        "f1": round(float(f1), 4),
    }


def best_f1_threshold(y: np.ndarray, p: np.ndarray) -> float:
    """The score threshold with the highest F1 (precision and recall balanced)."""
    precision, recall, thresholds = precision_recall_curve(y, p)
    # precision_recall_curve returns one more precision/recall point than thresholds.
    precision, recall = precision[:-1], recall[:-1]
    with np.errstate(invalid="ignore", divide="ignore"):
        f1 = np.where(precision + recall > 0, 2 * precision * recall / (precision + recall), 0)
    return float(thresholds[int(np.argmax(f1))])


def all_metrics(y: np.ndarray, p: np.ndarray, threshold: float | None = None) -> dict:
    y = np.asarray(y, dtype=int)
    p = np.asarray(p, dtype=float)
    metrics = {
        "orders": int(y.size),
        "late_rate": round(float(y.mean()), 4),
        "mean_predicted": round(float(p.mean()), 4),
        "pr_auc": round(float(average_precision_score(y, p)), 4),
        "roc_auc": round(float(roc_auc_score(y, p)), 4),
        "brier": round(float(brier_score_loss(y, p)), 4),
        "log_loss": round(float(log_loss(y, np.clip(p, EPSILON, 1 - EPSILON))), 4),
        "ece": round(expected_calibration_error(y, p), 4),
    }
    if threshold is not None:
        metrics["at_threshold"] = threshold_metrics(y, p, threshold)
    return metrics


class PlattCalibrator:
    """Recalibrate scores: a logistic regression on the score's log-odds.

    Fitted on validation data, so that probabilities reflect the late rate of the
    recent period (2018) rather than only the training period (2017).
    """

    def __init__(self) -> None:
        self.model = LogisticRegression(C=1e6, max_iter=1000)

    @staticmethod
    def _log_odds(p: np.ndarray) -> np.ndarray:
        p = np.clip(np.asarray(p, dtype=float), EPSILON, 1 - EPSILON)
        return np.log(p / (1 - p)).reshape(-1, 1)

    def fit(self, y: np.ndarray, p: np.ndarray) -> "PlattCalibrator":
        self.model.fit(self._log_odds(p), np.asarray(y, dtype=int))
        return self

    def predict(self, p: np.ndarray) -> np.ndarray:
        return self.model.predict_proba(self._log_odds(p))[:, 1]

    def to_dict(self) -> dict[str, float]:
        """slope and intercept: calibrated = sigmoid(intercept + slope * log_odds(score))."""
        return {
            "slope": float(self.model.coef_[0, 0]),
            "intercept": float(self.model.intercept_[0]),
        }
