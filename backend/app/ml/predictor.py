"""Predictor template - for regression and generic predict."""
import pandas as pd
from sklearn.ensemble import RandomForestRegressor
from sklearn.metrics import mean_squared_error
from .preprocessing import train_test_split_simple

def train_regressor(df: pd.DataFrame, target: str):
    (X_train, X_test, y_train, y_test), columns = train_test_split_simple(df, target)
    model = RandomForestRegressor(random_state=42)
    model.fit(X_train, y_train)
    pred = model.predict(X_test)
    rmse = (mean_squared_error(y_test, pred) ** 0.5)
    return {"model": model, "columns": columns, "rmse": rmse}

def predict_single(model, columns, input_dict: dict):
    df = pd.DataFrame([input_dict])
    df = pd.get_dummies(df)
    for c in columns:
        if c not in df.columns:
            df[c] = 0
    df = df[columns]
    return model.predict(df)[0]
