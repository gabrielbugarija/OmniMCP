from typing import Optional, Literal, List

from pynput import keyboard, mouse

from .types import Bounds


class InputController:
    """Internal input control for MCP tools"""

    def __init__(self):
        self.mouse = mouse.Controller()
        self.keyboard = keyboard.Controller()

    async def click(
        self, bounds: Bounds, click_type: Literal["single", "double", "right"]
    ) -> bool:
        """Execute click at normalized coordinates"""
        x = bounds.x + (bounds.width / 2)
        y = bounds.y + (bounds.height / 2)
        self.mouse.position = (x, y)

        if click_type == "single":
            self.mouse.click(mouse.Button.left, 1)
        elif click_type == "double":
            self.mouse.click(mouse.Button.left, 2)
        elif click_type == "right":
            self.mouse.click(mouse.Button.right, 1)
        return True

    async def type_text(self, text: str) -> bool:
        """Type text using keyboard"""
        self.keyboard.type(text)
        return True

    async def press_key(self, key: str, modifiers: Optional[List[str]] = None) -> bool:
        """Press key with optional modifiers"""
        if modifiers:
            for mod in modifiers:
                self.keyboard.press(getattr(keyboard.Key, mod))
        self.keyboard.press(key)
        self.keyboard.release(key)
        if modifiers:
            for mod in modifiers:
                self.keyboard.release(getattr(keyboard.Key, mod))
        return True
