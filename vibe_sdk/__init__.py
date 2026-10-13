DIRECTION_DELTAS = {
    "NORTH": (0, -1),
    "SOUTH": (0, 1),
    "EAST": (1, 0),
    "WEST": (-1, 0),
    "NORTHEAST": (1, -1),
    "NORTHWEST": (-1, -1),
    "SOUTHEAST": (1, 1),
    "SOUTHWEST": (-1, 1),
}


class Action:
    __slots__ = ("kind", "direction", "target")

    def __init__(self, kind, direction=None, target=None):
        self.kind = kind
        self.direction = direction
        self.target = target

    @classmethod
    def move(cls, direction):
        return cls("move", direction=direction)

    @classmethod
    def attack(cls, bot_id):
        return cls("attack", target=bot_id)

    @classmethod
    def shoot(cls, direction):
        return cls("shoot", direction=direction)

    @classmethod
    def collect(cls):
        return cls("collect")

    @classmethod
    def defend(cls):
        return cls("defend")

    @classmethod
    def scan(cls):
        return cls("scan")

    @classmethod
    def ability(cls, direction=None):
        return cls("ability", direction=direction)

    @classmethod
    def use_item(cls, direction=None):
        return cls("use_item", direction=direction)

    def __repr__(self):
        return f"Action({self.kind!r}, direction={self.direction!r}, target={self.target!r})"


class Bot:
    ABILITY = None
    ROLE = None

    def decide(self, view):
        raise NotImplementedError

    def buy(self, shop):
        return None
