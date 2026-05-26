"""
train_model.py
--------------
Trains and evaluates both a Decision Tree and Random Forest classifier
on the maintenance request dataset. Saves the best performing model
as a .pkl file ready for later Django integration.

Run from the same folder as maintenance_requests_dataset.csv
"""

import pandas as pd
import numpy as np
import joblib
import os

from sklearn.model_selection import train_test_split, GridSearchCV, cross_val_score
from sklearn.preprocessing import LabelEncoder
from sklearn.tree import DecisionTreeClassifier
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import (
    accuracy_score,
    classification_report,
    confusion_matrix,
    ConfusionMatrixDisplay
)
import matplotlib.pyplot as plt
import warnings
warnings.filterwarnings("ignore")

# ─────────────────────────────────────────────────────────────────────
# ABSOLUTE PATHS — works no matter where you run the script from
# ─────────────────────────────────────────────────────────────────────

# Directory where this script lives: ml_model/scripts/
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

# ml_model/ folder — one level up from scripts/
ML_DIR     = os.path.dirname(SCRIPT_DIR)

# Paths to data, saved model output, and chart output
DATA_PATH  = os.path.join(ML_DIR, "data", "maintenance_requests_dataset.csv")
SAVE_DIR   = os.path.join(ML_DIR, "saved_model")
CHARTS_DIR = os.path.join(ML_DIR, "charts")

os.makedirs(SAVE_DIR,   exist_ok=True)
os.makedirs(CHARTS_DIR, exist_ok=True)

print("=" * 60)
print("  MAINTENANCE REQUEST PRIORITY CLASSIFIER - TRAINING")
print("=" * 60)
print(f"\nData   : {DATA_PATH}")
print(f"Models : {SAVE_DIR}")

# ─────────────────────────────────────────────────────────────────────
# STEP 1: Load dataset
# ─────────────────────────────────────────────────────────────────────

df = pd.read_csv(DATA_PATH)

print(f"\n✔ Dataset loaded: {len(df)} records, {df.shape[1]} columns")
print("\nPriority distribution:")
print(df["priority_label"].value_counts())

# ─────────────────────────────────────────────────────────────────────
# STEP 2: Preprocessing — encode categorical features
# ─────────────────────────────────────────────────────────────────────

# One-hot encode: request_category and location
df_encoded = pd.get_dummies(df, columns=["request_category", "location"])

# Encode target label
label_encoder = LabelEncoder()
df_encoded["priority_label"] = label_encoder.fit_transform(df_encoded["priority_label"])

# Class mapping for reference
class_mapping = dict(zip(
    label_encoder.transform(label_encoder.classes_),
    label_encoder.classes_
))
print(f"\nClass encoding: {class_mapping}")

# ─────────────────────────────────────────────────────────────────────
# STEP 3: Split features and target
# ─────────────────────────────────────────────────────────────────────

X = df_encoded.drop(columns=["priority_label"])
y = df_encoded["priority_label"]

# Save feature column names for later use in Django
feature_columns = X.columns.tolist()

# Stratified split — 80% train, 20% test
X_train, X_test, y_train, y_test = train_test_split(
    X, y, test_size=0.2, random_state=42, stratify=y
)

print(f"\nTraining set : {len(X_train)} records")
print(f"Test set     : {len(X_test)} records")

# ─────────────────────────────────────────────────────────────────────
# STEP 4: Train Decision Tree with hyperparameter tuning
# ─────────────────────────────────────────────────────────────────────

print("\n" + "─" * 60)
print("  TRAINING DECISION TREE")
print("─" * 60)

dt_params = {
    "max_depth"        : [3, 5, 7, 10, None],
    "min_samples_split": [2, 5, 10],
    "min_samples_leaf" : [1, 2, 4],
    "criterion"        : ["gini", "entropy"],
}

dt_grid = GridSearchCV(
    DecisionTreeClassifier(random_state=42),
    dt_params,
    cv=5,
    scoring="f1_weighted",
    n_jobs=-1
)
dt_grid.fit(X_train, y_train)
best_dt = dt_grid.best_estimator_

print(f"Best parameters : {dt_grid.best_params_}")

dt_preds = best_dt.predict(X_test)
dt_accuracy = accuracy_score(y_test, dt_preds)

print(f"\nDecision Tree Test Accuracy: {dt_accuracy * 100:.2f}%")
print("\nClassification Report:")
print(classification_report(
    y_test, dt_preds,
    target_names=label_encoder.classes_
))

# Cross-validation score
dt_cv = cross_val_score(best_dt, X, y, cv=5, scoring="accuracy")
print(f"Cross-validation accuracy: {dt_cv.mean() * 100:.2f}% (+/- {dt_cv.std() * 100:.2f}%)")

# ─────────────────────────────────────────────────────────────────────
# STEP 5: Train Random Forest with hyperparameter tuning
# ─────────────────────────────────────────────────────────────────────

print("\n" + "─" * 60)
print("  TRAINING RANDOM FOREST")
print("─" * 60)

rf_params = {
    "n_estimators"     : [50, 100, 200],
    "max_depth"        : [5, 10, None],
    "min_samples_split": [2, 5],
    "min_samples_leaf" : [1, 2],
}

rf_grid = GridSearchCV(
    RandomForestClassifier(random_state=42),
    rf_params,
    cv=5,
    scoring="f1_weighted",
    n_jobs=-1
)
rf_grid.fit(X_train, y_train)
best_rf = rf_grid.best_estimator_

print(f"Best parameters : {rf_grid.best_params_}")

rf_preds = best_rf.predict(X_test)
rf_accuracy = accuracy_score(y_test, rf_preds)

print(f"\nRandom Forest Test Accuracy: {rf_accuracy * 100:.2f}%")
print("\nClassification Report:")
print(classification_report(
    y_test, rf_preds,
    target_names=label_encoder.classes_
))

# Cross-validation score
rf_cv = cross_val_score(best_rf, X, y, cv=5, scoring="accuracy")
print(f"Cross-validation accuracy: {rf_cv.mean() * 100:.2f}% (+/- {rf_cv.std() * 100:.2f}%)")

# ─────────────────────────────────────────────────────────────────────
# STEP 6: Compare and pick best model
# ─────────────────────────────────────────────────────────────────────

print("\n" + "=" * 60)
print("  MODEL COMPARISON")
print("=" * 60)
print(f"  Decision Tree  accuracy : {dt_accuracy * 100:.2f}%")
print(f"  Random Forest  accuracy : {rf_accuracy * 100:.2f}%")

if rf_accuracy >= dt_accuracy:
    best_model = best_rf
    best_model_name = "Random Forest"
    best_preds = rf_preds
    print(f"\n  ✔ Best model selected: Random Forest")
else:
    best_model = best_dt
    best_model_name = "Decision Tree"
    best_preds = dt_preds
    print(f"\n  ✔ Best model selected: Decision Tree")

# ─────────────────────────────────────────────────────────────────────
# STEP 7: Plot confusion matrix for best model
# ─────────────────────────────────────────────────────────────────────

cm = confusion_matrix(y_test, best_preds)
disp = ConfusionMatrixDisplay(
    confusion_matrix=cm,
    display_labels=label_encoder.classes_
)

fig, ax = plt.subplots(figsize=(7, 6))
disp.plot(ax=ax, colorbar=True, cmap="Blues")
ax.set_title(f"Confusion Matrix — {best_model_name}", fontsize=13, fontweight="bold")
plt.tight_layout()
plt.savefig(os.path.join(CHARTS_DIR, "confusion_matrix.png"), dpi=150)
plt.close()
print("\n✔ Confusion matrix saved → confusion_matrix.png")

# ─────────────────────────────────────────────────────────────────────
# STEP 8: Feature importance chart (best model)
# ─────────────────────────────────────────────────────────────────────

importances = best_model.feature_importances_
feat_imp = pd.Series(importances, index=feature_columns).sort_values(ascending=False).head(10)

fig, ax = plt.subplots(figsize=(8, 5))
feat_imp.plot(kind="bar", ax=ax, color="#2E75B6", edgecolor="white")
ax.set_title(f"Top 10 Feature Importances — {best_model_name}", fontsize=12, fontweight="bold")
ax.set_ylabel("Importance Score")
ax.set_xlabel("Feature")
plt.xticks(rotation=35, ha="right", fontsize=9)
plt.tight_layout()
plt.savefig(os.path.join(CHARTS_DIR, "feature_importance.png"), dpi=150)
plt.close()
print("✔ Feature importance chart saved → feature_importance.png")

# ─────────────────────────────────────────────────────────────────────
# STEP 9: Save model, encoder and feature columns
# ─────────────────────────────────────────────────────────────────────

joblib.dump(best_model,      os.path.join(SAVE_DIR, "priority_classifier.pkl"))
joblib.dump(label_encoder,   os.path.join(SAVE_DIR, "label_encoder.pkl"))
joblib.dump(feature_columns, os.path.join(SAVE_DIR, "feature_columns.pkl"))

print(f"\n✔ Model saved         → {os.path.join(SAVE_DIR, 'priority_classifier.pkl')}")
print(f"✔ Label encoder saved → {os.path.join(SAVE_DIR, 'label_encoder.pkl')}")
print(f"✔ Feature columns saved → {os.path.join(SAVE_DIR, 'feature_columns.pkl')}")

# ─────────────────────────────────────────────────────────────────────
# STEP 10: Quick sanity check — predict a sample request
# ─────────────────────────────────────────────────────────────────────

print("\n" + "─" * 60)
print("  SANITY CHECK — Sample Predictions")
print("─" * 60)

sample_requests = [
    {
        "request_category": "Electrical",
        "location": "Room",
        "urgency_level": 5,
        "affected_users": 4,
        "time_sensitivity": 1,
        "impact_level": 3,
        "recurrence": 1,
        "expected": "High"
    },
    {
        "request_category": "Plumbing",
        "location": "Bathroom",
        "urgency_level": 3,
        "affected_users": 2,
        "time_sensitivity": 0,
        "impact_level": 2,
        "recurrence": 0,
        "expected": "Medium"
    },
    {
        "request_category": "Furniture",
        "location": "Room",
        "urgency_level": 2,
        "affected_users": 1,
        "time_sensitivity": 0,
        "impact_level": 1,
        "recurrence": 0,
        "expected": "Low"
    },
]

for i, req in enumerate(sample_requests, 1):
    expected = req.pop("expected")
    sample_df = pd.DataFrame([req])
    sample_encoded = pd.get_dummies(sample_df, columns=["request_category", "location"])

    # Align columns to match training features
    sample_encoded = sample_encoded.reindex(columns=feature_columns, fill_value=0)

    prediction_encoded = best_model.predict(sample_encoded)[0]
    prediction = label_encoder.inverse_transform([prediction_encoded])[0]

    status = "✔" if prediction == expected else "✗"
    print(f"  Sample {i}: Predicted = {prediction:<8}  Expected = {expected:<8}  {status}")

print("\n" + "=" * 60)
print("  TRAINING COMPLETE")
print("=" * 60)
