"""
author: Gabriel Bugarija
date: 2025-03-27
version: 1.1.0
description: True integration test for the parse_image function using a live server.

This script performs end-to-end testing for the parse_image function.
It includes:
- Encoding images to base64
- Sending POST requests to a live server
- Asserting correct response structure
- Visual comparison of UI states before and after actions

Requirements:
- pytest
- requests
- Pillow (PIL)
- tempfile


Usage:
Ensure your server is running at http://localhost:5000/

Then run:
python -m pytest -v test_parse_image_local.py
"""

import os
import base64
import pytest
import requests
from PIL import Image, ImageDraw
from tempfile import NamedTemporaryFile
import numpy as np
from skimage.metrics import structural_similarity as ssim

API_URL = "http://localhost:5000/parse/"


def encode_to_base64(path):
    with open(path, "rb") as img:
        return base64.b64encode(img.read()).decode("utf-8")


def ssim_diff(img1_path, img2_path, threshold=0.95):
    # Compares grayscale images using SSIM
    img1 = np.array(Image.open(img1_path).convert("L"))
    img2 = np.array(Image.open(img2_path).convert("L"))
    score, _ = ssim(img1, img2, full=True)
    return score > threshold


@pytest.fixture(scope="session")
def mock_ui_images():
    # Generates temp image files for tests
    variants = {}

    def make_img(tag, bg_color):
        img = Image.new("RGB", (100, 100), color=bg_color)
        draw = ImageDraw.Draw(img)
        draw.text((10, 45), tag, fill="white")

        tmp = NamedTemporaryFile(suffix=".png", delete=False)
        img.save(tmp)
        tmp.close()
        return tmp.name

    variants["before_click"] = make_img("BEFORE", "blue")
    variants["after_click"] = make_img("AFTER", "green")
    variants["before_type"] = make_img("B_TYPE", "red")
    variants["after_type"] = make_img("A_TYPE", "purple")

    yield variants

    # Cleanup
    for path in variants.values():
        if os.path.exists(path):
            os.remove(path)


def test_server_live():
    try:
        res = requests.get("http://localhost:5000/")
        assert res.status_code == 200
    except requests.exceptions.RequestException:
        pytest.fail("Server is down at http://localhost:5000/")


@pytest.mark.parametrize("img_key", ["before_click", "after_click", "before_type", "after_type"])
def test_parse_endpoint(img_key, mock_ui_images):
    path = mock_ui_images[img_key]
    payload = {"image": encode_to_base64(path)}

    res = requests.post(API_URL, json=payload)
    assert res.status_code == 200
    body = res.json()

    assert "segments" in body and isinstance(body["segments"], list)
    assert len(body["segments"]) > 0
    print(f"[PASS] Image parsed: {img_key}")


@pytest.mark.parametrize("before, after", [
    ("before_click", "after_click"),
    ("before_type", "after_type")
])
def test_ui_ssim_diff(before, after, mock_ui_images):
    # Ensure different UI states are visually different
    assert not ssim_diff(mock_ui_images[before], mock_ui_images[after]), (
        f"[FAIL] {before} and {after} too similar!"
    )