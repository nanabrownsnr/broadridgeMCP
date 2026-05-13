from pathlib import Path

import joblib
import numpy as np
from app.core.config import settings
from app.schemas.classifier import BatchClassifyRequest, ClassifyTextRequest, TrainExamplesRequest
from fastapi import APIRouter, HTTPException
from sklearn.feature_extraction.text import HashingVectorizer
from sklearn.linear_model import SGDClassifier
from sklearn.preprocessing import LabelEncoder

router = APIRouter(prefix="/classifier", tags=["classifier"])


class TextClassifierEngine:
    def __init__(self) -> None:
        self.labels = [x.strip() for x in settings.LABELS_CSV.split(",") if x.strip()]
        self.vectorizer = HashingVectorizer(ngram_range=(1, 2), n_features=2**18, alternate_sign=False, norm="l2")
        self.model = SGDClassifier(loss="log_loss", alpha=1e-5, random_state=42)
        self.label_encoder = LabelEncoder()
        self.label_encoder.fit(self.labels)
        self.is_fitted = False
        self.model_store_path = Path(settings.MODEL_STORE_PATH)
        self._seed_if_needed()
        self._load_if_exists()

    def _seed_if_needed(self) -> None:
        if self.is_fitted:
            return
        seed_data = {
            "backend_bug": ["api returns 500", "database timeout", "null pointer in service", "backend validation fails"],
            "frontend_bug": ["button not clickable", "ui layout broken", "react error on page", "css overlap issue"],
            "missing_feature": ["need add export csv", "please add dark mode", "feature request for approval workflow"],
            "integration_issue": ["webhook fails", "jira sync not working", "api integration error"],
            "data_issue": ["incorrect entitlement data", "duplicate records", "missing issuer fields"],
            "performance_issue": ["dashboard loads slowly", "high latency in search", "query too slow"],
            "security_issue": ["xss risk in comment field", "auth bypass suspected", "permission check missing"],
            "devops_issue": ["deployment failed", "container crash loop", "pipeline error"],
            "needs_review": ["not sure what issue type this is", "general concern needs triage"],
        }
        texts: list[str] = []
        ys: list[str] = []
        for label, samples in seed_data.items():
            for sample in samples:
                texts.append(sample)
                ys.append(label)
        self._fit(texts, ys)

    def _fit(self, texts: list[str], labels: list[str]) -> None:
        X = self.vectorizer.transform(texts)
        y = self.label_encoder.transform(labels)
        self.model.partial_fit(X, y, classes=np.arange(len(self.labels)))
        self.is_fitted = True

    def _save(self) -> None:
        self.model_store_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"model": self.model, "labels": self.labels}
        joblib.dump(payload, self.model_store_path)

    def _load_if_exists(self) -> None:
        if not self.model_store_path.exists():
            self._save()
            return
        payload = joblib.load(self.model_store_path)
        if payload and isinstance(payload, dict) and "model" in payload:
            self.model = payload["model"]
            persisted_labels = payload.get("labels") or self.labels
            self.labels = persisted_labels
            self.label_encoder.fit(self.labels)
            self.is_fitted = True

    def classify(self, text: str, top_k: int) -> dict:
        if not text.strip():
            raise HTTPException(status_code=400, detail="text must not be empty")
        X = self.vectorizer.transform([text])
        probs = self.model.predict_proba(X)[0]
        idxs = np.argsort(probs)[::-1][:top_k]
        top = [{"label": self.labels[i], "score": float(round(probs[i], 4))} for i in idxs]
        return {"label": top[0]["label"], "score": top[0]["score"], "top_k": top}

    def classify_batch(self, texts: list[str], top_k: int) -> list[dict]:
        return [self.classify(text, top_k) for text in texts]

    def train_examples(self, examples: list[dict]) -> dict:
        texts = [e["text"].strip() for e in examples if e["text"].strip()]
        labels = [e["label"].strip() for e in examples if e["text"].strip()]
        unknown = [label for label in labels if label not in self.labels]
        if unknown:
            raise HTTPException(status_code=400, detail=f"Unknown labels: {sorted(set(unknown))}")
        if not texts:
            raise HTTPException(status_code=400, detail="No valid training examples provided")
        self._fit(texts, labels)
        self._save()
        return {"trained_examples": len(texts), "labels": self.labels}

    def model_info(self) -> dict:
        return {
            "model_type": "HashingVectorizer + SGDClassifier(log_loss)",
            "cpu_optimized": True,
            "labels": self.labels,
            "model_store_path": str(self.model_store_path),
        }


ENGINE = TextClassifierEngine()


@router.post("/classify_text", operation_id="classify_text")
async def classify_text(payload: ClassifyTextRequest) -> dict:
    """
    Classify one IT triage text into labels like backend_bug, frontend_bug, or missing_feature.
    """
    return ENGINE.classify(payload.text, payload.top_k)


@router.post("/batch_classify", operation_id="batch_classify")
async def batch_classify(payload: BatchClassifyRequest) -> dict:
    """
    Classify multiple text items in one request for high-throughput triage.
    """
    if not payload.texts:
        raise HTTPException(status_code=400, detail="texts must not be empty")
    return {"results": ENGINE.classify_batch(payload.texts, payload.top_k)}


@router.post("/train_examples", operation_id="train_examples")
async def train_examples(payload: TrainExamplesRequest) -> dict:
    """
    Incrementally train the classifier with project-specific labeled examples.
    """
    return ENGINE.train_examples([x.model_dump() for x in payload.examples])


@router.get("/labels", operation_id="labels")
async def labels() -> dict:
    """
    Return supported classification labels for routing and validation.
    """
    return {"labels": ENGINE.labels}


@router.get("/model_info", operation_id="model_info")
async def model_info() -> dict:
    """
    Return model/backend metadata and deployment details.
    """
    return ENGINE.model_info()
