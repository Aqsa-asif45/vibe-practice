import random

from vibe_sdk import DIRECTION_DELTAS, Action, Bot

HOLD_LIMIT = 4
MOVE_COST = 1
COLLECT_COST = 2
BLOCKED_LIMIT = 2


class MyBot(Bot):
    ABILITY = None
    ROLE = None

    def __init__(self):
        self.rng = random.Random(7)
        self.last_pos = None
        self.last_dir = None
        self.blocked_count = 0

    def decide(self, view):
        me = view["self"]
        here = (me["x"], me["y"])

        if self.last_dir is not None:
            self.blocked_count = self.blocked_count + 1 if here == self.last_pos else 0
        self.last_pos = here

        action = self.plan(view, me, here)
        self.last_dir = action.direction if action.kind == "move" else None
        return action

    def plan(self, view, me, here):
        board = view["board"]
        walls = {(w["x"], w["y"]) for w in view["walls"]}
        resources = [(r["x"], r["y"]) for r in view["visible_resources"]]

        if me["cargo"] >= HOLD_LIMIT:
            target = (me["base"]["x"], me["base"]["y"])
            return self.step(me, target, walls, board)

        if here in resources and me["energy"] >= COLLECT_COST:
            return Action.collect()

        if resources:
            target = min(resources, key=lambda r: (self.distance(here, r), r))
        else:
            target = (board["width"] // 2, board["height"] // 2)
        return self.step(me, target, walls, board)

    def step(self, me, target, walls, board):
        here = (me["x"], me["y"])
        if here == target or me["energy"] < MOVE_COST:
            return Action.defend()
        options = []
        for name, (dx, dy) in DIRECTION_DELTAS.items():
            nxt = (here[0] + dx, here[1] + dy)
            if not (0 <= nxt[0] < board["width"] and 0 <= nxt[1] < board["height"]):
                continue
            if nxt in walls or self.cuts_corner(here, dx, dy, walls):
                continue
            options.append((self.distance(nxt, target), name))
        if not options:
            return Action.defend()
        if self.blocked_count >= BLOCKED_LIMIT:
            others = sorted(name for _, name in options if name != self.last_dir)
            if others:
                return Action.move(self.rng.choice(others))
        return Action.move(min(options, key=lambda o: o[0])[1])

    def cuts_corner(self, here, dx, dy, walls):
        return bool(dx and dy and (here[0] + dx, here[1]) in walls and (here[0], here[1] + dy) in walls)

    def distance(self, a, b):
        return max(abs(a[0] - b[0]), abs(a[1] - b[1]))
