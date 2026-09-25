"""
Vision service - OPTIONAL, lazy OpenCV/HuggingFace.
Works offline without installing large models.
"""
import logging
from typing import Optional

logger = logging.getLogger("hackathon.vision")

class VisionService:
    def __init__(self):
        self.enabled = True
        logger.info("VisionService init (lazy - models loaded on demand)")

    def is_opencv_available(self) -> bool:
        try:
            import cv2
            return True
        except ImportError:
            return False

    def is_transformers_available(self) -> bool:
        try:
            import transformers
            return True
        except ImportError:
            return False

    async def analyze_image(self, image_path: str, prompt: Optional[str] = None) -> dict:
        """Template for image analysis. Tomorrow plug YOLO/HF model here."""
        result = {
            "image": image_path,
            "prompt": prompt or "Analyze image",
            "opencv_available": self.is_opencv_available(),
            "transformers_available": self.is_transformers_available(),
            "detections": [],
            "note": "Vision template - add YOLO/transformers inference tomorrow if problem requires. Install: pip install ultralytics transformers opencv-python"
        }
        # Example offline logic if opencv present: basic stats
        if self.is_opencv_available():
            try:
                import cv2
                img = cv2.imread(image_path)
                if img is not None:
                    h, w, c = img.shape
                    result["image_info"] = {"height": h, "width": w, "channels": c}
                    result["detections"].append({"label": "image_loaded", "confidence": 1.0, "bbox": [0,0,w,h]})
            except Exception as e:
                result["error"] = str(e)
        return result

def get_vision() -> VisionService:
    return VisionService()
