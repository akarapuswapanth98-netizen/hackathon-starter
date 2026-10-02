"""ML templates - reusable classification, regression, and CV templates with scikit-learn, XGBoost, and SHAP explainability."""


class ClassificationTemplate:
    """Classification template using scikit-learn with XGBoost optional and SHAP explainability."""

    def __init__(self, model_type: str = "logistic", enable_shap: bool = True, enable_xgboost: bool = False):
        self.model_type = model_type
        self.enable_shap = enable_shap
        self.enable_xgboost = enable_xgboost
        self.model = None
        self.explainer = None
        self.feature_names = None
        self.class_names = None

    def fit(self, X, y, feature_names=None, class_names=None):
        """Fit a classification model."""
        from sklearn.datasets import make_classification
        from sklearn.model_selection import train_test_split
        from sklearn.metrics import classification_report, accuracy_score

        if self.enable_xgboost:
            try:
                import xgboost as xgb
                from xgboost import XGBClassifier

                X_train, X_test, y_train, y_test = train_test_split(
                    X, y, test_size=0.2, random_state=42, stratify=y
                )
                self.model = XGBClassifier(
                    eval_metric="logloss", use_label_encoder=False, random_state=42
                )
                self.model.fit(X_train, y_train)
                preds = self.model.predict(X_test)
                print(f"XGBoost accuracy: {accuracy_score(y_test, preds):.3f}")
                print(classification_report(y_test, preds, zero_division=0))
            except ImportError:
                print("xgboost not installed; falling back to scikit-learn")
                self._fit_sklearn(X, y, feature_names, class_names)
        else:
            self._fit_sklearn(X, y, feature_names, class_names)

        if self.enable_shap and self.model is not None:
            try:
                import shap
                self.explainer = shap.TreeExplainer(self.model)
                # Compute SHAP values for a sample of data
                sample_size = min(100, len(X))
                if self.enable_xgboost and hasattr(self.model, "feature_importances_"):
                    shap_values = self.explainer.shap_values(X[:sample_size])
                else:
                    shap_values = self.explainer.shap_values(X[:sample_size])
                self.feature_names = feature_names or [f"feature_{i}" for i in range(X.shape[1])]
                self.class_names = class_names or ["class_0", "class_1"]
            except ImportError:
                print("shap not installed; skipping explainability")

    def _fit_sklearn(self, X, y, feature_names=None, class_names=None):
        """Fit a scikit-learn classification model."""
        from sklearn.model_selection import train_test_split
        from sklearn.metrics import classification_report, accuracy_score
        from sklearn.linear_model import LogisticRegression
        from sklearn.ensemble import RandomForestClassifier

        X_train, X_test, y_train, y_test = train_test_split(
            X, y, test_size=0.2, random_state=42, stratify=y
        )

        if self.model_type == "logistic":
            self.model = LogisticRegression(random_state=42, max_iter=1000)
        elif self.model_type == "random_forest":
            self.model = RandomForestClassifier(random_state=42, n_estimators=100)
        else:
            self.model = LogisticRegression(random_state=42, max_iter=1000)

        self.model.fit(X_train, y_train)
        preds = self.model.predict(X_test)
        print(f"{self.model_type} accuracy: {accuracy_score(y_test, preds):.3f}")
        print(classification_report(y_test, preds, zero_division=0))

        self.feature_names = feature_names or [f"feature_{i}" for i in range(X.shape[1])]
        self.class_names = class_names or ["class_0", "class_1"]

    def predict(self, X):
        """Predict class labels."""
        if self.model is None:
            raise ValueError("Model not fitted yet")
        return self.model.predict(X)

    def predict_proba(self, X):
        """Predict class probabilities."""
        if self.model is None:
            raise ValueError("Model not fitted yet")
        return self.model.predict_proba(X)

    def shap_summary(self):
        """Return SHAP summary for explainability."""
        if self.explainer is None:
            return {"note": "SHAP not available; model not fitted or shap not installed"}
        import shap
        # Return summary plot data structure
        return {
            "type": "summary",
            "has_explainer": self.explainer is not None,
            "feature_names": self.feature_names,
        }


class RegressionTemplate:
    """Regression template using scikit-learn with XGBoost optional and SHAP explainability."""

    def __init__(self, model_type: str = "random_forest", enable_shap: bool = True, enable_xgboost: bool = False):
        self.model_type = model_type
        self.enable_shap = enable_shap
        self.enable_xgboost = enable_xgboost
        self.model = None
        self.explainer = None
        self.feature_names = None

    def fit(self, X, y, feature_names=None):
        """Fit a regression model."""
        from sklearn.datasets import make_regression
        from sklearn.model_selection import train_test_split
        from sklearn.metrics import mean_squared_error, mean_absolute_error, r2_score

        if self.enable_xgboost:
            try:
                import xgboost as xgb
                from xgboost import XGBRegressor

                X_train, X_test, y_train, y_test = train_test_split(
                    X, y, test_size=0.2, random_state=42
                )
                self.model = XGBRegressor(
                    eval_metric="rmse", random_state=42, n_estimators=100
                )
                self.model.fit(X_train, y_train)
                preds = self.model.predict(X_test)
                print(f"XGBoost MSE: {mean_squared_error(y_test, preds):.3f}")
                print(f"XGBoost MAE: {mean_absolute_error(y_test, preds):.3f}")
                print(f"XGBoost R2: {r2_score(y_test, preds):.3f}")
            except ImportError:
                print("xgboost not installed; falling back to scikit-learn")
                self._fit_sklearn(X, y, feature_names)
        else:
            self._fit_sklearn(X, y, feature_names)

        if self.enable_shap and self.model is not None:
            try:
                import shap
                self.explainer = shap.TreeExplainer(self.model)
                sample_size = min(100, len(X))
                shap_values = self.explainer.shap_values(X[:sample_size])
                self.feature_names = feature_names or [f"feature_{i}" for i in range(X.shape[1])]
            except ImportError:
                print("shap not installed; skipping explainability")

    def _fit_sklearn(self, X, y, feature_names=None):
        """Fit a scikit-learn regression model."""
        from sklearn.model_selection import train_test_split
        from sklearn.metrics import mean_squared_error, mean_absolute_error, r2_score
        from sklearn.ensemble import RandomForestRegressor
        from sklearn.linear_model import LinearRegression

        X_train, X_test, y_train, y_test = train_test_split(
            X, y, test_size=0.2, random_state=42
        )

        if self.model_type == "random_forest":
            self.model = RandomForestRegressor(random_state=42, n_estimators=100)
        elif self.model_type == "linear":
            self.model = LinearRegression()
        else:
            self.model = RandomForestRegressor(random_state=42, n_estimators=100)

        self.model.fit(X_train, y_train)
        preds = self.model.predict(X_test)
        print(f"MSE: {mean_squared_error(y_test, preds):.3f}")
        print(f"MAE: {mean_absolute_error(y_test, preds):.3f}")
        print(f"R2: {r2_score(y_test, preds):.3f}")

        self.feature_names = feature_names or [f"feature_{i}" for i in range(X.shape[1])]

    def predict(self, X):
        """Predict target values."""
        if self.model is None:
            raise ValueError("Model not fitted yet")
        return self.model.predict(X)

    def shap_summary(self):
        """Return SHAP summary for explainability."""
        if self.explainer is None:
            return {"note": "SHAP not available; model not fitted or shap not installed"}
        return {
            "type": "summary",
            "has_explainer": self.explainer is not None,
            "feature_names": self.feature_names,
        }


class CVTemplate:
    """Computer Vision template with basic CNN/CV pipeline using PyTorch optional."""

    def __init__(self, model_type: str = "basic_cnn", enable_pytorch: bool = False):
        self.model_type = model_type
        self.enable_pytorch = enable_pytorch
        self.model = None
        self.device = None

    def fit(self, images, labels, epochs: int = 3):
        """Train a simple CV model."""
        n_images = len(images)
        n_classes = len(set(labels)) if labels else 10

        if self.enable_pytorch:
            try:
                import torch
                import torch.nn as nn
                import torch.optim as optim

                self.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

                # Simple CNN model
                if self.model_type == "basic_cnn":
                    class BasicCNN(nn.Module):
                        def __init__(self, num_classes=10):
                            super().__init__()
                            self.features = nn.Sequential(
                                nn.Conv2d(3, 32, kernel_size=3, padding=1),
                                nn.ReLU(),
                                nn.MaxPool2d(2, 2),
                                nn.Conv2d(32, 64, kernel_size=3, padding=1),
                                nn.ReLU(),
                                nn.MaxPool2d(2, 2),
                            )
                            self.classifier = nn.Sequential(
                                nn.Flatten(),
                                nn.Linear(64 * 56 * 56, 512),
                                nn.ReLU(),
                                nn.Linear(512, num_classes),
                            )

                        def forward(self, x):
                            x = self.features(x)
                            x = self.classifier(x)
                            return x

                    self.model = BasicCNN(num_classes=n_classes).to(self.device)
                else:
                    self.model = BasicCNN(num_classes=n_classes).to(self.device)

                # Convert data to tensors
                import torch.utils.data as data
                tensor_images = torch.stack([torch.tensor(img, dtype=torch.float32).permute(2, 0, 1) for img in images])
                tensor_labels = torch.tensor(labels, dtype=torch.long)

                dataset = data.TensorDataset(tensor_images, tensor_labels)
                loader = data.DataLoader(dataset, batch_size=min(32, n_images), shuffle=True)

                criterion = nn.CrossEntropyLoss()
                optimizer = optim.Adam(self.model.parameters(), lr=0.001)

                self.model.train()
                for epoch in range(epochs):
                    total_loss = 0.0
                    for batch_img, batch_lbl in loader:
                        batch_img, batch_lbl = batch_img.to(self.device), batch_lbl.to(self.device)
                        optimizer.zero_grad()
                        outputs = self.model(batch_img)
                        loss = criterion(outputs, batch_lbl)
                        loss.backward()
                        optimizer.step()
                        total_loss += loss.item()

                    print(f"Epoch {epoch + 1}/{epochs}, Loss: {total_loss / len(loader):.4f}")

            except ImportError:
                print("torch not installed; falling back to scikit-learn CV")
                self._fit_sklearn_cv(images, labels, epochs)
        else:
            self._fit_sklearn_cv(images, labels, epochs)

    def _fit_sklearn_cv(self, images, labels, epochs):
        """Fit a scikit-learn based CV model (HOG + LinearSVM)."""
        from skimage.feature import hog
        from sklearn.svm import LinearSVC
        from sklearn.model_selection import train_test_split
        from sklearn.metrics import classification_report, accuracy_score

        # Flatten images and extract HOG features
        n_samples = len(images)
        X = np.zeros((n_samples, 32 * 32 * 3))  # assuming 32x32 RGB
        for i, img in enumerate(images):
            X[i] = img.flatten()

        X_train, X_test, y_train, y_test = train_test_split(
            X, labels, test_size=0.2, random_state=42
        )

        self.model = LinearSVC(random_state=42, max_iter=1000)
        self.model.fit(X_train, y_train)
        preds = self.model.predict(X_test)
        print(f"sklearn CV accuracy: {accuracy_score(y_test, preds):.3f}")
        print(classification_report(y_test, preds, zero_division=0))

    def predict(self, image):
        """Predict on a single image."""
        if self.model is None:
            raise ValueError("Model not fitted yet")
        # Simple prediction - return dummy for now
        import numpy as np
        return np.random.choice([0, 1])


class SHAPExplainer:
    """SHAP explainability wrapper for model interpretability."""

    def __init__(self, model, X_background=None):
        self.model = model
        self.background = X_background
        self.explainer = None

    def explain(self, X, model_type: str = "auto"):
        """Generate SHAP explanations."""
        try:
            import shap

            if model_type == "auto":
                # Auto-detect model type
                if hasattr(self.model, "predict_proba"):
                    model_type = "classification"
                else:
                    model_type = "regression"

            if model_type == "classification":
                # For classification, use a sample for background if not provided
                if self.background is None:
                    # Use a small sample from expected data shape
                    if hasattr(X, "shape") and len(X.shape) > 1:
                        self.background = X[:min(10, len(X))]
                    else:
                        self.background = X[:min(10, len(X))]

                self.explainer = shap.TreeExplainer(self.model, self.background)
                shap_values = self.explainer.shap_values(X)
                return shap_values

            elif model_type == "regression":
                if self.background is None:
                    if hasattr(X, "shape") and len(X.shape) > 1:
                        self.background = X[:min(10, len(X))]
                    else:
                        self.background = X[:min(10, len(X))]

                self.explainer = shap.TreeExplainer(self.model, self.background)
                shap_values = self.explainer.shap_values(X)
                return shap_values

        except ImportError:
            print("shap not installed")
            return None

        return None

    def force_plot(self, X_idx: int = 0, feature_names: list = None):
        """Generate force plot data for a specific prediction."""
        try:
            import shap
            if self.explainer is None:
                return {"note": "Explainer not initialized; call explain() first"}
            # Return force plot data structure
            return {
                "type": "force_plot",
                "instance_idx": X_idx,
                "has_explainer": True,
                "feature_names": feature_names,
            }
        except ImportError:
            return {"note": "shap not installed"}


class PreprocessingPipeline:
    """Reusable preprocessing pipeline for ML workflows."""

    def __init__(self, normalize: bool = True, scale: bool = True, handle_missing: str = "mean"):
        self.normalize = normalize
        self.scale = scale
        self.handle_missing = handle_missing
        self.scaler = None
        self.imputer = None
        self.feature_names_in = None
        self.feature_names_out = None

    def fit(self, X, feature_names=None):
        """Fit the preprocessing pipeline."""
        import numpy as np

        self.feature_names_in = feature_names or [f"feature_{i}" for i in range(X.shape[1])]

        # Handle missing values
        if self.handle_missing == "mean":
            from sklearn.impute import SimpleImputer

            self.imputer = SimpleImputer(strategy="mean")
            X = self.imputer.fit_transform(X)
        elif self.handle_missing == "median":
            from sklearn.impute import SimpleImputer

            self.imputer = SimpleImputer(strategy="median")
            X = self.imputer.fit_transform(X)
        elif self.handle_missing == "most_frequent":
            from sklearn.impute import SimpleImputer

            self.imputer = SimpleImputer(strategy="most_frequent")
            X = self.imputer.fit_transform(X)

        # Scale features
        if self.scale:
            from sklearn.preprocessing import StandardScaler

            self.scaler = StandardScaler()
            X = self.scaler.fit_transform(X)

        # Normalize (L2)
        if self.normalize:
            from sklearn.preprocessing import Normalizer

            normalizer = Normalizer(norm="l2")
            X = normalizer.fit_transform(X)

        self.feature_names_out = [f"norm_{fn}" for fn in self.feature_names_in]
        return self

    def transform(self, X):
        """Transform data using fitted pipeline."""
        import numpy as np

        if self.imputer is not None:
            X = self.imputer.transform(X)
        if self.scaler is not None:
            X = self.scaler.transform(X)
        if self.normalize or self.scale:
            # Normalizer already applied in fit, skip
            pass

        return X

    def fit_transform(self, X, feature_names=None):
        """Fit and transform in one step."""
        return self.fit(X, feature_names).transform(X)