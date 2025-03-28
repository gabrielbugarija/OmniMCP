# omnimcp/synthetic_ui.py
import os
from typing import List, Tuple
from PIL import Image, ImageDraw, ImageFont

from .types import UIElement, Bounds
from .utils import logger  # Reuse logger from utils

# Attempt to load a default font, handle potential errors
try:
    # Adjust path if needed, or use a system font finder
    FONT = ImageFont.truetype("arial.ttf", 15)
except IOError:
    logger.warning("Arial font not found. Using default PIL font.")
    FONT = ImageFont.load_default()

IMG_WIDTH, IMG_HEIGHT = 800, 600


def _bounds_to_abs(bounds: Bounds) -> Tuple[int, int, int, int]:
    """Convert normalized bounds to absolute pixel coordinates."""
    x, y, w, h = bounds
    abs_x = int(x * IMG_WIDTH)
    abs_y = int(y * IMG_HEIGHT)
    abs_w = int(w * IMG_WIDTH)
    abs_h = int(h * IMG_HEIGHT)
    return abs_x, abs_y, abs_w, abs_h


def generate_login_screen(
    save_path: str | None = None,
) -> Tuple[Image.Image, List[UIElement]]:
    """Generates a synthetic login screen image and element data."""
    img = Image.new(
        "RGB", (IMG_WIDTH, IMG_HEIGHT), color=(230, 230, 230)
    )  # Light gray background
    draw = ImageDraw.Draw(img)
    elements: List[UIElement] = []
    element_id_counter = 0

    # Title
    title_text = "Welcome Back!"
    title_bbox = draw.textbbox((0, 0), title_text, font=FONT)
    title_w = title_bbox[2] - title_bbox[0]
    title_h = title_bbox[3] - title_bbox[1]
    title_x = (IMG_WIDTH - title_w) / 2
    title_y = 80
    draw.text((title_x, title_y), title_text, fill="black", font=FONT)
    # Note: Pure text isn't usually an 'element' for interaction, but can be included
    # elements.append(UIElement(...)) # Optional: Add static text if needed by model

    # Username Field
    uname_label_y = 150
    uname_field_y = uname_label_y + 25
    uname_x = 200
    uname_w = 400
    uname_h = 40
    draw.text((uname_x, uname_label_y), "Username:", fill="black", font=FONT)
    draw.rectangle(
        [(uname_x, uname_field_y), (uname_x + uname_w, uname_field_y + uname_h)],
        fill="white",
        outline="black",
    )
    elements.append(
        UIElement(
            id=element_id_counter,
            type="text_field",
            content="",  # Empty field
            bounds=(
                uname_x / IMG_WIDTH,
                uname_field_y / IMG_HEIGHT,
                uname_w / IMG_WIDTH,
                uname_h / IMG_HEIGHT,
            ),
        )
    )
    element_id_counter += 1

    # Password Field
    pw_label_y = uname_field_y + uname_h + 20
    pw_field_y = pw_label_y + 25
    pw_x = 200
    pw_w = 400
    pw_h = 40
    draw.text((pw_x, pw_label_y), "Password:", fill="black", font=FONT)
    draw.rectangle(
        [(pw_x, pw_field_y), (pw_x + pw_w, pw_field_y + pw_h)],
        fill="white",
        outline="black",
    )
    elements.append(
        UIElement(
            id=element_id_counter,
            type="text_field",
            content="",  # Empty field, often masked
            bounds=(
                pw_x / IMG_WIDTH,
                pw_field_y / IMG_HEIGHT,
                pw_w / IMG_WIDTH,
                pw_h / IMG_HEIGHT,
            ),
            attributes={"is_password": True},
        )
    )
    element_id_counter += 1

    # Remember Me Checkbox
    cb_y = pw_field_y + pw_h + 30
    cb_x = 200
    cb_size = 20
    cb_text_x = cb_x + cb_size + 10
    draw.rectangle(
        [(cb_x, cb_y), (cb_x + cb_size, cb_y + cb_size)], fill="white", outline="black"
    )
    draw.text((cb_text_x, cb_y + 2), "Remember Me", fill="black", font=FONT)
    elements.append(
        UIElement(
            id=element_id_counter,
            type="checkbox",
            content="Remember Me",
            bounds=(
                cb_x / IMG_WIDTH,
                cb_y / IMG_HEIGHT,
                cb_size / IMG_WIDTH,
                cb_size / IMG_HEIGHT,
            ),
            attributes={"checked": False},
        )
    )
    element_id_counter += 1

    # Forgot Password Link
    fp_text = "Forgot Password?"
    fp_bbox = draw.textbbox((0, 0), fp_text, font=FONT)
    fp_w = fp_bbox[2] - fp_bbox[0]
    fp_h = fp_bbox[3] - fp_bbox[1]
    fp_x = pw_x + pw_w - fp_w  # Align right
    fp_y = cb_y + 5  # Align with checkbox text
    draw.text((fp_x, fp_y), fp_text, fill="blue", font=FONT)
    elements.append(
        UIElement(
            id=element_id_counter,
            type="link",
            content="Forgot Password?",
            bounds=(
                fp_x / IMG_WIDTH,
                fp_y / IMG_HEIGHT,
                fp_w / IMG_WIDTH,
                fp_h / IMG_HEIGHT,
            ),
        )
    )
    element_id_counter += 1

    # Login Button
    btn_y = cb_y + cb_size + 40
    btn_w = 120
    btn_h = 45
    btn_x = (IMG_WIDTH - btn_w) / 2
    draw.rectangle(
        [(btn_x, btn_y), (btn_x + btn_w, btn_y + btn_h)], fill="green", outline="black"
    )
    btn_text = "Login"
    btn_bbox = draw.textbbox((0, 0), btn_text, font=FONT)
    btn_text_w = btn_bbox[2] - btn_bbox[0]
    btn_text_h = btn_bbox[3] - btn_bbox[1]
    draw.text(
        (btn_x + (btn_w - btn_text_w) / 2, btn_y + (btn_h - btn_text_h) / 2),
        btn_text,
        fill="white",
        font=FONT,
    )
    elements.append(
        UIElement(
            id=element_id_counter,
            type="button",
            content="Login",
            bounds=(
                btn_x / IMG_WIDTH,
                btn_y / IMG_HEIGHT,
                btn_w / IMG_WIDTH,
                btn_h / IMG_HEIGHT,
            ),
        )
    )
    element_id_counter += 1

    if save_path:
        os.makedirs(os.path.dirname(os.path.abspath(save_path)), exist_ok=True)
        img.save(save_path)
        logger.info(f"Saved synthetic UI to {save_path}")

    return img, elements


def draw_highlight(
    image: Image.Image, element: UIElement, color: str = "red", width: int = 3
) -> Image.Image:
    """Draws a highlight box around the specified element on the image."""
    img_copy = image.copy()
    draw = ImageDraw.Draw(img_copy)
    abs_x, abs_y, abs_w, abs_h = _bounds_to_abs(element.bounds)

    # Draw rectangle outline
    draw.rectangle(
        [(abs_x, abs_y), (abs_x + abs_w, abs_y + abs_h)], outline=color, width=width
    )
    return img_copy


# Note: The idea of LLM generating PIL code for screenshots is interesting but complex.
# Adding LLM-based generation would require:
# 1. A prompt asking the LLM to write Python PIL code based on a description.
# 2. Secure execution of the generated code (e.g., using restricted execution
#    environments).
# 3. Parsing the output (the image and potentially element data if the LLM generates
#    it).
# This adds multiple points of failure and significant development time.
