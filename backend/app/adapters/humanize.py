import random
import time
from collections.abc import Callable


class Humanizer:
    """Random, human-like pacing. `scale=0` disables all waiting (used in tests)."""

    def __init__(
        self,
        rng: random.Random | None = None,
        sleep: Callable[[float], None] = time.sleep,
        scale: float = 1.0,
    ):
        self.rng = rng or random.Random()
        self._sleep = sleep
        self.scale = scale

    def pause(self, lo: float = 0.6, hi: float = 2.2) -> float:
        d = self.rng.uniform(lo, hi) * self.scale
        if d > 0:
            self._sleep(d)
        return d

    def type_into(self, locator, text: str) -> None:
        locator.click()
        if self.scale == 0 or len(text) > 200:
            locator.fill(text)
        else:
            locator.fill("")
            locator.press_sequentially(text, delay=self.rng.randint(35, 110))
        self.pause(0.2, 0.7)

    def click(self, locator) -> None:
        self.pause(0.3, 1.0)
        locator.click()
