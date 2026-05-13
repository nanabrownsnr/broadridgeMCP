import json
from pathlib import Path

import joblib
import numpy as np
from app.core.config import settings
from app.schemas.classifier import (
    BatchClassifyRequest,
    ClassifyTextRequest,
    CreateTaxonomyRequest,
    TrainExamplesRequest,
    UpdateTaxonomyRequest,
)
from fastapi import APIRouter, HTTPException
from sklearn.feature_extraction.text import HashingVectorizer
from sklearn.linear_model import SGDClassifier
from sklearn.preprocessing import LabelEncoder

router = APIRouter(prefix="/classifier", tags=["classifier"])


DEFAULT_TAXONOMIES = {
    "twynity_tickets": {
        "taxonomy_id": "twynity_tickets",
        "display_name": "Twynity Tickets",
        "description": "Ticket triage taxonomy for Twynity AI engineering issues.",
        "confidence_threshold": 0.75,
        "labels": [
            "backend_bug",
            "frontend_bug",
            "missing_feature",
            "integration_issue",
            "data_issue",
            "performance_issue",
            "security_issue",
            "devops_issue",
            "needs_review",
        ],
    },
    "hr_tickets": {
        "taxonomy_id": "hr_tickets",
        "display_name": "HR Tickets",
        "description": "HR request taxonomy for internal people-ops workflows.",
        "confidence_threshold": 0.75,
        "labels": [
            "benefits",
            "payroll_question",
            "leave_request",
            "policy_question",
            "onboarding",
            "offboarding",
            "manager_change",
            "employee_data_update",
            "needs_review",
        ],
    },
}


class TaxonomyClassifierManager:
    def __init__(self) -> None:
        model_path = Path(settings.MODEL_STORE_PATH)
        self.store_dir = model_path.parent
        self.store_dir.mkdir(parents=True, exist_ok=True)
        self.taxonomy_store = self.store_dir / "taxonomies.json"
        self.vectorizer = HashingVectorizer(ngram_range=(1, 2), n_features=2**18, alternate_sign=False, norm="l2")
        self.taxonomies = self._load_taxonomies()
        self.models: dict[str, dict] = {}

    def _load_taxonomies(self) -> dict:
        if not self.taxonomy_store.exists():
            self.taxonomy_store.write_text(json.dumps(DEFAULT_TAXONOMIES, indent=2), encoding="utf-8")
            return dict(DEFAULT_TAXONOMIES)
        return json.loads(self.taxonomy_store.read_text(encoding="utf-8"))

    def _save_taxonomies(self) -> None:
        self.taxonomy_store.write_text(json.dumps(self.taxonomies, indent=2), encoding="utf-8")

    def _model_file(self, taxonomy_id: str) -> Path:
        return self.store_dir / f"{taxonomy_id}.joblib"

    def _seed_samples(self, taxonomy_id: str) -> dict[str, list[str]]:
        if taxonomy_id == "hr_tickets":
            return {
                "benefits": ["question about health insurance", "need dental benefits info"],
                "payroll_question": ["salary not received", "payroll deduction looks wrong"],
                "leave_request": ["request vacation leave", "apply for sick leave"],
                "policy_question": ["clarify remote work policy", "question on expense policy"],
                "onboarding": ["new hire onboarding access", "onboarding checklist request"],
                "offboarding": ["employee exit process", "offboarding account closure"],
                "manager_change": ["update reporting manager", "team transfer to new manager"],
                "employee_data_update": ["change home address", "update bank account details"],
                "needs_review": ["general hr issue not sure category"],
            }
        return {
            "backend_bug": ["api returns 500", "database timeout", "null pointer in service"],
            "frontend_bug": ["button not clickable", "ui layout broken", "react page error"],
            "missing_feature": ["need export csv", "please add dark mode"],
            "integration_issue": ["webhook fails", "jira sync not working"],
            "data_issue": ["duplicate records", "missing issuer fields"],
            "performance_issue": ["dashboard loads slowly", "search latency high"],
            "security_issue": ["xss risk found", "permission check missing"],
            "devops_issue": ["deployment failed", "pipeline error"],
            "needs_review": ["unclear issue category"],
        }

    def _ensure_engine(self, taxonomy_id: str) -> dict:
        if taxonomy_id not in self.taxonomies:
            raise HTTPException(status_code=404, detail=f"Unknown taxonomy: {taxonomy_id}")
        if taxonomy_id in self.models:
            return self.models[taxonomy_id]

        labels = self.taxonomies[taxonomy_id]["labels"]
        label_encoder = LabelEncoder()
        label_encoder.fit(labels)
        model_file = self._model_file(taxonomy_id)
        if model_file.exists():
            payload = joblib.load(model_file)
            model = payload["model"]
            persisted_labels = payload.get("labels", labels)
            label_encoder.fit(persisted_labels)
            labels = persisted_labels
        else:
            model = SGDClassifier(loss="log_loss", alpha=1e-5, random_state=42)
            seed = self._seed_samples(taxonomy_id)
            texts: list[str] = []
            ys: list[str] = []
            for label, samples in seed.items():
                if label not in labels:
                    continue
                for sample in samples:
                    texts.append(sample)
                    ys.append(label)
            X = self.vectorizer.transform(texts)
            y = label_encoder.transform(ys)
            model.partial_fit(X, y, classes=np.arange(len(labels)))
            joblib.dump({"model": model, "labels": labels}, model_file)

        self.models[taxonomy_id] = {"model": model, "labels": labels, "encoder": label_encoder}
        return self.models[taxonomy_id]

    def list_taxonomies(self) -> list[dict]:
        return list(self.taxonomies.values())

    def get_taxonomy(self, taxonomy_id: str) -> dict:
        if taxonomy_id not in self.taxonomies:
            raise HTTPException(status_code=404, detail=f"Unknown taxonomy: {taxonomy_id}")
        return self.taxonomies[taxonomy_id]

    def create_taxonomy(self, taxonomy: dict) -> dict:
        taxonomy_id = taxonomy["taxonomy_id"]
        if taxonomy_id in self.taxonomies:
            raise HTTPException(status_code=409, detail=f"Taxonomy already exists: {taxonomy_id}")
        if len(set(taxonomy["labels"])) != len(taxonomy["labels"]):
            raise HTTPException(status_code=400, detail="Labels must be unique")
        self.taxonomies[taxonomy_id] = taxonomy
        self._save_taxonomies()
        self.models.pop(taxonomy_id, None)
        return taxonomy

    def update_taxonomy(self, payload: UpdateTaxonomyRequest) -> dict:
        taxonomy_id = payload.taxonomy_id
        if taxonomy_id not in self.taxonomies:
            raise HTTPException(status_code=404, detail=f"Unknown taxonomy: {taxonomy_id}")
        item = self.taxonomies[taxonomy_id]
        if payload.display_name is not None:
            item["display_name"] = payload.display_name
        if payload.description is not None:
            item["description"] = payload.description
        if payload.confidence_threshold is not None:
            item["confidence_threshold"] = payload.confidence_threshold
        if payload.labels is not None:
            if len(set(payload.labels)) != len(payload.labels):
                raise HTTPException(status_code=400, detail="Labels must be unique")
            item["labels"] = payload.labels
            # Reset model cache; retraining required for new label space.
            self.models.pop(taxonomy_id, None)
            model_file = self._model_file(taxonomy_id)
            if model_file.exists():
                model_file.unlink()
        self.taxonomies[taxonomy_id] = item
        self._save_taxonomies()
        return item

    def classify(self, taxonomy_id: str, text: str, top_k: int) -> dict:
        if not text.strip():
            raise HTTPException(status_code=400, detail="text must not be empty")
        engine = self._ensure_engine(taxonomy_id)
        labels = engine["labels"]
        model = engine["model"]
        X = self.vectorizer.transform([text])
        probs = model.predict_proba(X)[0]
        idxs = np.argsort(probs)[::-1][: min(top_k, len(labels))]
        top = [{"label": labels[i], "score": float(round(probs[i], 4))} for i in idxs]
        threshold = float(self.taxonomies[taxonomy_id].get("confidence_threshold", 0.75))
        return {
            "taxonomy_id": taxonomy_id,
            "label": top[0]["label"],
            "score": top[0]["score"],
            "high_confidence": top[0]["score"] >= threshold,
            "confidence_threshold": threshold,
            "top_k": top,
        }

    def classify_batch(self, taxonomy_id: str, texts: list[str], top_k: int) -> list[dict]:
        return [self.classify(taxonomy_id, t, top_k) for t in texts]

    def train_examples(self, taxonomy_id: str, examples: list[dict]) -> dict:
        engine = self._ensure_engine(taxonomy_id)
        labels = engine["labels"]
        model = engine["model"]
        label_encoder = engine["encoder"]

        texts = [e["text"].strip() for e in examples if e["text"].strip()]
        ys = [e["label"].strip() for e in examples if e["text"].strip()]
        unknown = [label for label in ys if label not in labels]
        if unknown:
            raise HTTPException(status_code=400, detail=f"Unknown labels for taxonomy {taxonomy_id}: {sorted(set(unknown))}")
        if not texts:
            raise HTTPException(status_code=400, detail="No valid training examples provided")

        X = self.vectorizer.transform(texts)
        y = label_encoder.transform(ys)
        model.partial_fit(X, y, classes=np.arange(len(labels)))
        joblib.dump({"model": model, "labels": labels}, self._model_file(taxonomy_id))
        return {"taxonomy_id": taxonomy_id, "trained_examples": len(texts), "labels": labels}

    def model_info(self, taxonomy_id: str) -> dict:
        self._ensure_engine(taxonomy_id)
        return {
            "taxonomy_id": taxonomy_id,
            "model_type": "HashingVectorizer + SGDClassifier(log_loss)",
            "cpu_optimized": True,
            "labels": self.taxonomies[taxonomy_id]["labels"],
            "confidence_threshold": self.taxonomies[taxonomy_id].get("confidence_threshold", 0.75),
            "model_store_path": str(self._model_file(taxonomy_id)),
            "taxonomy_store_path": str(self.taxonomy_store),
        }


MANAGER = TaxonomyClassifierManager()


@router.get("/taxonomies", operation_id="list_taxonomies")
async def list_taxonomies() -> dict:
    """List all available taxonomies (locked label sets)."""
    return {"taxonomies": MANAGER.list_taxonomies()}


@router.get("/taxonomies/{taxonomy_id}", operation_id="get_taxonomy")
async def get_taxonomy(taxonomy_id: str) -> dict:
    """Get one taxonomy definition by ID."""
    return MANAGER.get_taxonomy(taxonomy_id)


@router.post("/taxonomies/create", operation_id="create_taxonomy")
async def create_taxonomy(payload: CreateTaxonomyRequest) -> dict:
    """Create a new taxonomy for another domain (e.g., hr_tickets, finance_requests)."""
    return MANAGER.create_taxonomy(payload.taxonomy.model_dump())


@router.post("/taxonomies/update", operation_id="update_taxonomy")
async def update_taxonomy(payload: UpdateTaxonomyRequest) -> dict:
    """Update taxonomy labels/metadata. Changing labels resets that taxonomy model file."""
    return MANAGER.update_taxonomy(payload)


@router.post("/classify_text", operation_id="classify_text")
async def classify_text(payload: ClassifyTextRequest) -> dict:
    """
    Classify one ticket/request under a selected taxonomy.

    Workflow note:
    1. If output label is `needs_review`, ask a human to choose the final label.
    2. Submit the corrected sample via `train_examples`.
    """
    return MANAGER.classify(payload.taxonomy_id, payload.text, payload.top_k)


@router.post("/batch_classify", operation_id="batch_classify")
async def batch_classify(payload: BatchClassifyRequest) -> dict:
    """
    Batch classify multiple items under one taxonomy.

    Workflow note:
    1. Capture low-confidence/needs_review results.
    2. Feed human-confirmed labels to `train_examples`.
    """
    if not payload.texts:
        raise HTTPException(status_code=400, detail="texts must not be empty")
    return {"taxonomy_id": payload.taxonomy_id, "results": MANAGER.classify_batch(payload.taxonomy_id, payload.texts, payload.top_k)}


@router.post("/train_examples", operation_id="train_examples")
async def train_examples(payload: TrainExamplesRequest) -> dict:
    """
    Incrementally train one taxonomy model with human-labeled examples.

    Primary usage:
    1. Classifier returns `needs_review`.
    2. Human picks final label.
    3. Send `(text, label)` here to improve future predictions.
    """
    return MANAGER.train_examples(payload.taxonomy_id, [x.model_dump() for x in payload.examples])


@router.get("/labels/{taxonomy_id}", operation_id="labels")
async def labels(taxonomy_id: str) -> dict:
    """Return allowed labels for a taxonomy (validate before training)."""
    taxonomy = MANAGER.get_taxonomy(taxonomy_id)
    return {"taxonomy_id": taxonomy_id, "labels": taxonomy["labels"]}


@router.get("/model_info/{taxonomy_id}", operation_id="model_info")
async def model_info(taxonomy_id: str) -> dict:
    """Return backend/model metadata for a taxonomy."""
    return MANAGER.model_info(taxonomy_id)

