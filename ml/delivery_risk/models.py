"""The two late-delivery models compared in P3-T2 (settings fixed in advance).

(A) Logistic regression: the simple, explainable baseline the spec asks for.
(B) LightGBM: a tree model that can capture interactions (e.g. long distance AND
    a short promise).
Both return a late probability per order and are fitted on training data only.
"""

import lightgbm as lgb
import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline, make_pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

from delivery_risk.olist_data import CATEGORY_FEATURES, FEATURE_COLUMNS

NUMERIC_FEATURES = [c for c in FEATURE_COLUMNS if c not in CATEGORY_FEATURES]
OTHER_CATEGORIES = [c for c in CATEGORY_FEATURES if c != "product_category"]

LIGHTGBM_PARAMS = {
    "objective": "binary",
    "learning_rate": 0.05,
    "num_leaves": 63,
    "min_data_in_leaf": 100,
    "feature_fraction": 0.8,
    "bagging_fraction": 0.8,
    "bagging_freq": 1,
    "seed": 42,
    "deterministic": True,
    "num_threads": 4,
    "verbose": -1,
}
LIGHTGBM_ROUNDS = 400


def logistic_inputs(rows: pd.DataFrame) -> pd.DataFrame:
    """Feature columns with categories as plain text (what the one-hot encoder expects)."""
    inputs = rows[FEATURE_COLUMNS].copy()
    inputs[CATEGORY_FEATURES] = inputs[CATEGORY_FEATURES].astype(str)
    return inputs


def logistic_regression() -> Pipeline:
    """Median-impute and standardise numbers; one-hot encode categories.

    Product categories with fewer than 100 training orders share one "other"
    column, so rare categories cannot get extreme weights. Categories never seen
    in training are ignored (all their columns are 0).
    """
    numbers = make_pipeline(SimpleImputer(strategy="median"), StandardScaler())
    product_category = OneHotEncoder(
        handle_unknown="infrequent_if_exist", min_frequency=100, sparse_output=False
    )
    others = OneHotEncoder(handle_unknown="ignore", sparse_output=False)
    columns = ColumnTransformer(
        [
            ("numbers", numbers, NUMERIC_FEATURES),
            ("product_category", product_category, ["product_category"]),
            ("other_categories", others, OTHER_CATEGORIES),
        ]
    )
    return Pipeline([("columns", columns), ("model", LogisticRegression(C=1.0, max_iter=2000))])


def fit_logistic(train: pd.DataFrame) -> Pipeline:
    return logistic_regression().fit(logistic_inputs(train), train["late"])


def fit_lightgbm(train: pd.DataFrame) -> lgb.Booster:
    data = lgb.Dataset(
        train[FEATURE_COLUMNS], label=train["late"], categorical_feature=CATEGORY_FEATURES
    )
    return lgb.train(LIGHTGBM_PARAMS, data, num_boost_round=LIGHTGBM_ROUNDS)


def predict(model, rows: pd.DataFrame) -> np.ndarray:
    """Late probability for each row, for either model type."""
    if isinstance(model, lgb.Booster):
        return model.predict(rows[FEATURE_COLUMNS])
    return model.predict_proba(logistic_inputs(rows))[:, 1]


MODELS = {"logistic_regression": fit_logistic, "lightgbm": fit_lightgbm}
