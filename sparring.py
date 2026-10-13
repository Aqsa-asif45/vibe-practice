import random

from vibe_sdk import DIRECTION_DELTAS, Action, Bot


class MyBot(Bot):
    def __init__(self):
        self.rng = random.Random(7)

    def decide(self, view):
        roll = self.rng.random()
        enemies = view["visible_enemies"]
        if roll < 0.1:
            return None
        if roll < 0.25 and enemies:
            return Action.attack(self.rng.choice(enemies)["id"])
        if roll < 0.4:
            return Action.shoot(self.rng.choice(list(DIRECTION_DELTAS)))
        if roll < 0.5:
            return Action.defend()
        if roll < 0.55:
            return Action.collect()
        return Action.move(self.rng.choice(list(DIRECTION_DELTAS)))
