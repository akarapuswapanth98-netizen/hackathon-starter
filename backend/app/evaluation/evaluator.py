"""
Evaluator - lightweight, no fabricated scores.
Adapt after problem statement to real metrics.
"""
import time
from typing import Dict, Any
from .metrics import latency_ms, check_required_fields

class Evaluator:
    def __init__(self):
        self.runs: list = []

    async def evaluate_response(self, response: dict, required_fields: list = ["answer"]) -> Dict[str, Any]:
        start = time.time()
        checks = check_required_fields(response, required_fields)
        latency = latency_ms(start)
        result = {
            "valid": checks["passed"],
            "missing": checks["missing"],
            "latency_ms": latency,
            "has_answer": bool(response.get("answer")),
            "has_sources": bool(response.get("sources")),
        }
        self.runs.append(result)
        return result

    def summary(self) -> Dict:
        if not self.runs:
            return {"runs": 0}
        valid = sum(1 for r in self.runs if r["valid"])
        return {
            "runs": len(self.runs),
            "valid": valid,
            "invalid": len(self.runs)-valid,
            "avg_latency_ms": sum(r["latency_ms"] for r in self.runs)/len(self.runs)
        }

def get_evaluator() -> Evaluator:
    return Evaluator()
