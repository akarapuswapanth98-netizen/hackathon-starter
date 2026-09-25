"""Lightweight metrics - no fake accuracy."""
import time
from typing import Dict, List

def latency_ms(start: float) -> float:
    return (time.time() - start) * 1000

def check_required_fields(data: dict, required: List[str]) -> Dict:
    missing = [f for f in required if not data.get(f)]
    return {"missing": missing, "passed": len(missing)==0}

def retrieval_metrics(hits: List[dict], top_k: int = 3) -> Dict:
    return {"hits": len(hits), "top_k": top_k, "has_results": len(hits)>0}
