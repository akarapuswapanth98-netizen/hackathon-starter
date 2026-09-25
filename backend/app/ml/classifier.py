"""Classifier template - scikit-learn, no fake training."""
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import accuracy_score, classification_report
from .preprocessing import train_test_split_simple

def train_classifier(df: pd.DataFrame, target: str, n_estimators: int = 100):
    (X_train, X_test, y_train, y_test), columns = train_test_split_simple(df, target)
    model = RandomForestClassifier(n_estimators=n_estimators, random_state=42)
    model.fit(X_train, y_train)
    pred = model.predict(X_test)
    acc = accuracy_score(y_test, pred)
    report = classification_report(y_test, pred, output_dict=True, zero_division=0)
    return {"model": model, "columns": columns, "accuracy": acc, "report": report, "test_size": len(y_test)}
