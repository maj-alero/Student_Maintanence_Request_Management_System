# ml_model/classifier.py

import joblib
import pandas as pd
import os

# Build absolute paths so it works regardless of where Django is run from
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

MODEL_PATH   = os.path.join(BASE_DIR, "saved_model", "priority_classifier.pkl")
ENCODER_PATH = os.path.join(BASE_DIR, "saved_model", "label_encoder.pkl")
COLUMNS_PATH = os.path.join(BASE_DIR, "saved_model", "feature_columns.pkl")

# Load once when Django starts — not on every request
model           = joblib.load(MODEL_PATH)
label_encoder   = joblib.load(ENCODER_PATH)
feature_columns = joblib.load(COLUMNS_PATH)


def predict_priority(category, location, urgency_level,
                     affected_users, time_sensitivity,
                     impact_level, recurrence):
    """
    Takes raw form values and returns a priority label string.
    Returns: "High", "Medium", or "Low"
    """

    # Map form values to the same encoding used during training
    affected_map = {
        "Just me (1)"          : 1,
        "2-5 students"         : 2,
        "6-15 students"        : 3,
        "More than 15 students": 4,
    }

    input_data = {
        "request_category" : category,
        "location"         : location,
        "urgency_level"    : int(urgency_level),
        "affected_users"   : affected_map.get(affected_users, int(affected_users)),
        "time_sensitivity" : 1 if time_sensitivity in [True, 1, "Yes", "on"] else 0,
        "impact_level"     : int(impact_level),
        "recurrence"       : 1 if recurrence in [True, 1, "Yes", "on"] else 0,
    }

    # Build dataframe and one-hot encode
    df = pd.DataFrame([input_data])
    df_encoded = pd.get_dummies(df, columns=["request_category", "location"])

    # Align columns exactly to what the model was trained on
    df_encoded = df_encoded.reindex(columns=feature_columns, fill_value=0)

    # Predict and decode
    prediction_encoded = model.predict(df_encoded)[0]
    prediction = label_encoder.inverse_transform([prediction_encoded])[0]

    return prediction