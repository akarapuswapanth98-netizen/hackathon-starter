"""Vision templates - optional OpenCV/YOLO templates for object detection and image analysis."""


class YOLODetectionTemplate:
    """YOLO object detection template using ultralytics YOLO models.

    This template wraps the ultralytics YOLO model for object detection tasks.
    It can operate with or without PyTorch installed, falling back to basic
    OpenCV operations when YOLO is not available.
    """

    def __init__(self, model_name: str = "yolo11n.pt", confidence: float = 0.25, iou: float = 0.45):
        self.model_name = model_name
        self.confidence = confidence
        self.iou = iou
        self.model = None
        self.available = False

    def load_model(self):
        """Load the YOLO model."""
        try:
            from ultralytics import YOLO

            self.model = YOLO(self.model_name)
            self.available = True
            print(f"YOLO model '{self.model_name}' loaded successfully")
            return True
        except ImportError:
            print("ultralytics not installed; YOLO template unavailable")
            self.available = False
            return False
        except Exception as e:
            print(f"Failed to load YOLO model: {e}")
            self.available = False
            return False

    def detect(self, image_source, conf: float = None, iou: float = None):
        """Run object detection on an image.

        Args:
            image_source: Path to image file, numpy array, or video path
            conf: Confidence threshold (overrides self.confidence if provided)
            iou: IoU threshold (overrides self.iou if provided)

        Returns:
            Detection results dict or None if model not available
        """
        if not self.available:
            if not self.load_model():
                return None

        conf = self.confidence if conf is None else conf
        iou = self.iou if iou is None else iou

        try:
            if self.model is not None:
                results = self.model(image_source, conf=conf, iou=iou)
                # Return structured results
                result = results[0] if isinstance(results, list) else results
                return {
                    "plot": result.plot() if hasattr(result, "plot") else None,
                    "boxes": result.boxes if hasattr(result, "boxes") else [],
                    "masks": result.masks if hasattr(result, "masks") else None,
                    "probs": result.probs if hasattr(result, "probs") else None,
                    "obb": result.obb if hasattr(result, "obb") else None,
                }
        except Exception as e:
            print(f"Detection failed: {e}")
            return None

    def predict(self, image_path: str):
        """Predict on a single image file.

        Args:
            image_path: Path to image file

        Returns:
            Dictionary with detection results
        """
        return self.detect(image_path)


class OpenCVTemplate:
    """OpenCV-based vision template for image processing, feature detection, and basic analysis."""

    def __init__(self, use_gpu: bool = False):
        self.use_gpu = use_gpu
        self.available = True  # OpenCV is typically available

    def load_image(self, image_path: str) -> any:
        """Load an image from file.

        Args:
            image_path: Path to image file

        Returns:
            Image as numpy array (RGB format) or None if failed
        """
        import cv2

        img = cv2.imread(image_path)
        if img is None:
            print(f"Failed to load image: {image_path}")
            return None
        # Convert BGR to RGB
        img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
        return img

    def save_image(self, image: any, output_path: str):
        """Save an image to file.

        Args:
            image: Image as numpy array (RGB format)
            output_path: Path to save the image
        """
        import cv2

        # Convert RGB to BGR for OpenCV save
        img_bgr = cv2.cvtColor(image, cv2.COLOR_RGB2BGR)
        success = cv2.imwrite(output_path, img_bgr)
        if not success:
            print(f"Failed to save image: {output_path}")
        return success

    def resize(self, image: any, width: int, height: int) -> any:
        """Resize an image.

        Args:
            image: Image as numpy array
            width: Target width
            height: Target height

        Returns:
            Resized image as numpy array
        """
        import cv2

        return cv2.resize(image, (width, height))

    def grayscale(self, image: any) -> any:
        """Convert image to grayscale.

        Args:
            image: Image as numpy array (RGB format)

        Returns:
            Grayscale image as numpy array
        """
        import cv2

        return cv2.cvtColor(image, cv2.COLOR_RGB2GRAY)

    def detect_edges(self, image: any, threshold1: int = 100, threshold2: int = 200) -> any:
        """Detect edges using Canny edge detection.

        Args:
            image: Image as numpy array (RGB format)
            threshold1: Lower threshold for Canny
            threshold2: Upper threshold for Canny

        Returns:
            Edge-detected image as numpy array (grayscale)
        """
        import cv2

        gray = self.grayscale(image)
        edges = cv2.Canny(gray, threshold1, threshold2)
        return edges

    def find_contours(self, image: any, retrieval_mode: int = cv2.RETR_EXTERNAL,
                      approximation_method: int = cv2.CHAIN_APPROX_SIMPLE) -> list:
        """Find contours in a binary image.

        Args:
            image: Binary image (grayscale) as numpy array
            retrieval_mode: Contour retrieval mode
            approximation_method: Contour approximation method

        Returns:
            List of contours
        """
        import cv2

        # Ensure image is binary/grayscale
        if len(image.shape) == 3:
            gray = cv2.cvtColor(image, cv2.COLOR_RGB2GRAY)
        else:
            gray = image

        # Threshold if needed
        if gray.max() > 1:
            _, binary = cv2.threshold(gray, 127, 255, cv2.THRESH_BINARY)
        else:
            binary = gray

        contours, _ = cv2.findContours(binary, retrieval_mode, approximation_method)
        return contours

    def draw_bounding_boxes(self, image: any, boxes: list, color: tuple = (0, 255, 0), thickness: int = 2) -> any:
        """Draw bounding boxes on an image.

        Args:
            image: Image as numpy array (RGB format)
            boxes: List of [x, y, w, h] or [(x1, y1), (x2, y2)] format
            color: Box color in RGB format
            thickness: Line thickness

        Returns:
            Image with bounding boxes drawn
        """
        import cv2

        img = image.copy()
        for box in boxes:
            if len(box) == 4:
                x, y, w, h = box
                cv2.rectangle(img, (x, y), (x + w, y + h), color, thickness)
            elif len(box) == 2:
                # ((x1, y1), (x2, y2)) format
                pt1, pt2 = box
                cv2.rectangle(img, pt1, pt2, color, thickness)

        return img

    def resize_maintain_aspect(self, image: any, max_width: int, max_height: int) -> any:
        """Resize image maintaining aspect ratio.

        Args:
            image: Image as numpy array
            max_width: Maximum width
            max_height: Maximum height

        Returns:
            Resized image with aspect ratio maintained
        """
        import cv2

        h, w = image.shape[:2]

        # Calculate scaling factor
        scale = min(max_width / w, max_height / h, 1.0)
        if scale >= 1.0:
            return image  # No resizing needed

        new_w = int(w * scale)
        new_h = int(h * scale)

        return cv2.resize(image, (new_w, new_h))


class FaceDetectionTemplate:
    """Face detection template using Haar cascades (OpenCV built-in) or dlib."""

    def __init__(self, use_haar: bool = True):
        self.use_haar = use_haar
        self.face_cascade = None
        self.available = False

        if use_haar:
            try:
                import cv2

                # Load built-in Haar cascade for face detection
                self.face_cascade = cv2.CascadeClassifier(
                    cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
                )
                self.available = self.face_cascade is not None
                print("Haar cascade face detector loaded")
            except Exception as e:
                print(f"Failed to load Haar cascade: {e}")
                self.available = False

    def detect_faces(self, image: any) -> list:
        """Detect faces in an image.

        Args:
            image: Image as numpy array (RGB format) or file path

        Returns:
            List of face bounding boxes as [(x, y, w, h), ...]
        """
        if not self.available:
            print("Face detector not available")
            return []

        import cv2

        # Load image if file path provided
        if isinstance(image, str):
            img = self.load_image(image)
        else:
            img = image

        if img is None:
            return []

        # Convert to grayscale for Haar cascade
        if len(img.shape) == 3:
            gray = cv2.cvtColor(img, cv2.COLOR_RGB2GRAY)
        else:
            gray = img

        # Detect faces
        faces = self.face_cascade.detectMultiScale(
            gray,
            scaleFactor=1.1,
            minNeighbors=5,
            minSize=(30, 30),
        )

        # Convert to list of tuples
        face_list = [(int(x), int(y), int(w), int(h)) for (x, y, w, h) in faces]
        return face_list


class TemplateManager:
    """Manager for registering and switching between different vision templates."""

    def __init__(self):
        self.templates = {}
        self.default_template = "opencv"

    def register(self, name: str, template):
        """Register a vision template.

        Args:
            name: Template name
            template: Template instance
        """
        self.templates[name] = template
        print(f"Registered vision template: {name}")

    def get(self, name: str = None):
        """Get a vision template by name.

        Args:
            name: Template name (uses default if None)

        Returns:
            Template instance or None
        """
        name = name or self.default_template
        return self.templates.get(name)

    def detect(self, method: str, image_source, **kwargs):
        """Run detection using specified method.

        Args:
            method: Template name or "yolo", "opencv", "face"
            image_source: Image path or array
            **kwargs: Additional arguments for the template

        Returns:
            Detection results
        """
        if method in ("yolo", "YOLO", "yolo11n"):
            template = self.get("yolo")
            if template is None:
                # Try to load YOLO
                template = YOLODetectionTemplate()
                self.register("yolo", template)
            return template.detect(image_source, **kwargs)

        elif method in ("opencv", "OpenCV", "opencv_base"):
            template = self.get("opencv")
            if template is None:
                template = OpenCVTemplate()
                self.register("opencv", template)
            return template.detect(image_source, **kwargs)

        elif method in ("face", "Face", "face_haar"):
            template = self.get("face")
            if template is None:
                template = FaceDetectionTemplate()
                self.register("face", template)
            return template.detect_faces(image_source)

        else:
            # Default to OpenCV
            template = self.get("opencv")
            if template is None:
                template = OpenCVTemplate()
                self.register("opencv", template)
            return template.detect(image_source, **kwargs)