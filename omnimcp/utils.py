"""Minimal utilities needed for OmniMCP."""

from functools import wraps
from io import BytesIO
from typing import Any, Callable, Tuple, Union
import base64
import threading
import time
import textwrap

from jinja2 import Environment, Template
from loguru import logger
from PIL import Image
import mss

# Configure loguru
logger.add(
    "omnimcp.log",
    rotation="10 MB",
    retention="1 week",
    level="INFO",
    format="{time:YYYY-MM-DD HH:mm:ss} | {level} | {message}",
)

# Process-local storage for MSS instances
_process_local = threading.local()


def get_process_local_sct() -> mss.mss:
    """Retrieve or create the `mss` instance for the current process."""
    if not hasattr(_process_local, "sct"):
        _process_local.sct = mss.mss()
    return _process_local.sct


def take_screenshot() -> Image.Image:
    """Take a screenshot of the entire screen.

    Returns:
        PIL.Image.Image: The screenshot image
    """
    sct = get_process_local_sct()
    monitor = sct.monitors[0]
    sct_img = sct.grab(monitor)
    image = Image.frombytes("RGB", sct_img.size, sct_img.bgra, "raw", "BGRX")
    return image


def get_monitor_dims() -> Tuple[int, int]:
    """Get the dimensions of the primary monitor.

    Returns:
        tuple[int, int]: The width and height of the monitor
    """
    sct = get_process_local_sct()
    monitor = sct.monitors[0]
    return monitor["width"], monitor["height"]


def image_to_base64(image: Union[str, Image.Image]) -> str:
    """Convert image to base64 string.

    Args:
        image: PIL Image or path to image file

    Returns:
        str: Base64 encoded image string
    """
    if isinstance(image, str):
        image = Image.open(image)

    buffered = BytesIO()
    image.save(buffered, format="PNG")
    img_str = base64.b64encode(buffered.getvalue()).decode()
    return img_str


def log_action(func: Callable) -> Callable:
    """Decorator to log function calls with timing."""

    @wraps(func)
    def wrapper(*args: tuple, **kwargs: dict) -> Any:
        start = time.time()
        try:
            result = func(*args, **kwargs)
            duration = (time.time() - start) * 1000
            logger.debug(f"{func.__name__} completed in {duration:.2f}ms")
            return result
        except Exception as e:
            logger.error(f"{func.__name__} failed: {str(e)}")
            raise

    return wrapper


class MouseController:
    """Wrapper around pynput mouse control with logging."""

    def __init__(self):
        from pynput.mouse import Controller, Button

        self.controller = Controller()
        self.Button = Button

    @log_action
    def move(self, x: int, y: int):
        """Move mouse to absolute coordinates."""
        self.controller.position = (x, y)
        logger.debug(f"Mouse moved to ({x}, {y})")

    @log_action
    def click(self, button="left"):
        """Click the specified mouse button."""
        button = getattr(self.Button, button)
        self.controller.click(button)
        logger.debug(f"Mouse {button} click at {self.controller.position}")


class KeyboardController:
    """Wrapper around pynput keyboard control with logging."""

    def __init__(self):
        from pynput.keyboard import Controller, Key

        self.controller = Controller()
        self.Key = Key

    @log_action
    def type(self, text: str):
        """Type the specified text."""
        self.controller.type(text)
        logger.debug(f"Typed text: {text}")

    @log_action
    def press(self, key: str):
        """Press and release a key."""
        key = getattr(self.Key, key.lower(), key)
        self.controller.press(key)
        self.controller.release(key)
        logger.debug(f"Pressed key: {key}")


def normalize_coordinates(x: int, y: int) -> Tuple[float, float]:
    """Normalize coordinates to 0-1 range based on screen dimensions."""
    width, height = get_monitor_dims()
    return x / width, y / height


def denormalize_coordinates(x: float, y: float) -> Tuple[int, int]:
    """Convert normalized coordinates to absolute screen coordinates."""
    width, height = get_monitor_dims()
    return int(x * width), int(y * height)


def get_scale_ratios() -> Tuple[float, float]:
    """Get the scale ratios between actual screen dimensions and image dimensions.

    Handles high DPI/Retina displays where screenshot dimensions may differ from
    logical screen dimensions.

    Returns:
        tuple[float, float]: The (width_ratio, height_ratio) scaling factors.

    Example:
        # Convert screen coordinates to image coordinates
        width_ratio, height_ratio = get_scale_ratios()
        image_x = screen_x * width_ratio
        image_y = screen_y * height_ratio
    """
    # Get actual screen dimensions
    monitor_width, monitor_height = get_monitor_dims()

    # Get dimensions of screenshot image
    image = take_screenshot()

    # Calculate scaling ratios
    width_ratio = image.width / monitor_width
    height_ratio = image.height / monitor_height

    logger.debug(f"Scale ratios - width: {width_ratio:.2f}, height: {height_ratio:.2f}")
    return width_ratio, height_ratio


def screen_to_image_coords(x: int, y: int) -> Tuple[int, int]:
    """Convert screen coordinates to image coordinates.

    Args:
        x: Screen x coordinate
        y: Screen y coordinate

    Returns:
        tuple[int, int]: The (x, y) coordinates in image space
    """
    width_ratio, height_ratio = get_scale_ratios()
    image_x = int(x * width_ratio)
    image_y = int(y * height_ratio)
    return image_x, image_y


def image_to_screen_coords(x: int, y: int) -> Tuple[int, int]:
    """Convert image coordinates to screen coordinates.

    Args:
        x: Image x coordinate
        y: Image y coordinate

    Returns:
        tuple[int, int]: The (x, y) coordinates in screen space
    """
    width_ratio, height_ratio = get_scale_ratios()
    screen_x = int(x / width_ratio)
    screen_y = int(y / height_ratio)
    return screen_x, screen_y


def retry_with_exceptions(max_retries: int = 5) -> Callable:
    """Decorator to retry a function while keeping track of exceptions."""

    def decorator_retry(func: Callable) -> Callable:
        @wraps(func)
        def wrapper_retry(*args: tuple, **kwargs: dict[str, Any]) -> Any:
            exceptions = []
            retries = 0
            while retries < max_retries:
                try:
                    return func(*args, **kwargs)
                except Exception as exc:
                    logger.warning(exc)
                    exceptions.append(str(exc))
                    retries += 1
                    last_exception = exc
            raise RuntimeError(
                f"Failed after {max_retries} retries with exceptions: {exceptions}"
            ) from last_exception

        return wrapper_retry

    return decorator_retry


def compute_diff(image1: Image.Image, image2: Image.Image) -> Image.Image:
    """Computes the difference between two PIL Images.

    Useful for verifying UI changes after actions.

    Returns:
        PIL.Image.Image: Difference image showing changed pixels
    """
    import numpy as np

    arr1 = np.array(image1)
    arr2 = np.array(image2)
    diff = np.abs(arr1 - arr2)
    return Image.fromarray(diff.astype("uint8"))


def increase_contrast(image: Image.Image, contrast_factor: float = 1.5) -> Image.Image:
    """Increase the contrast of an image to help with UI element detection.

    Args:
        image: The image to enhance
        contrast_factor: Values > 1 increase contrast, < 1 decrease it

    Returns:
        Enhanced image
    """
    from PIL import ImageEnhance

    enhancer = ImageEnhance.Contrast(image)
    return enhancer.enhance(contrast_factor)


def create_prompt_template(template_str: str) -> Template:
    """Create a Jinja2 template from a multiline string.

    Handles proper dedenting and whitespace cleanup for clear template definitions.

    Args:
        template_str: Raw template string, can be triple-quoted multiline

    Returns:
        Jinja2 Template object ready for rendering

    Example:
        template = create_prompt_template('''
            Analyze this UI element and describe its properties:

            Screenshot context:
            {{ screenshot_desc }}

            Element bounds:
            {% for coord in coordinates %}
            - {{ coord }}
            {% endfor %}

            Previous actions:
            {% for action in action_history %}
            {{ loop.index }}. {{ action }}
            {% endfor %}
        ''')

        prompt = template.render(
            screenshot_desc=desc,
            coordinates=coords,
            action_history=history
        ).strip()
    """
    # Create Jinja environment with proper whitespace handling
    env = Environment(
        trim_blocks=True,
        lstrip_blocks=True,
    )

    # Dedent the template string to remove common leading whitespace
    template_str = textwrap.dedent(template_str)

    # Create and return the template
    return env.from_string(template_str)


def render_prompt(
    template_str: str,
    **kwargs: Any,
) -> str:
    """Create and render a prompt template in one step.

    Args:
        template_str: Raw template string
        **kwargs: Variables to render into template

    Returns:
        Rendered prompt string

    Example:
        prompt = render_prompt('''
            Analyze this UI element:
            {{ element_desc }}

            Coordinates: {% for c in coords %}{{ c }} {% endfor %}
        ''',
        element_desc="Blue button with text 'Submit'",
        coords=[10, 20, 30, 40]
        )
    """
    template = create_prompt_template(template_str)
    return template.render(**kwargs).strip()
