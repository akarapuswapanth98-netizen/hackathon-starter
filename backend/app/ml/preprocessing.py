"""ML preprocessing - reusable templates for hackathon."""
import pandas as pd
from typing import List, Tuple

def clean_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    # Strip whitespace, handle empty strings
    for col in df.select_dtypes(include="object").columns:
        df[col] = df[col].astype(str).str.strip()
    return df

def train_test_split_simple(df: pd.DataFrame, target: str, test_size: float = 0.2):
    from sklearn.model_selection import train_test_split
    X = df.drop(columns=[target])
    y = df[target]
    # One-hot for demo - tomorrow replace with proper pipeline if needed
    X = pd.get_dummies(X, drop_first=True)
    return train_test_split(X, y, test_size=test_size, random_state=42), X.columns.tolist()
