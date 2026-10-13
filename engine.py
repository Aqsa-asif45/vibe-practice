import importlib.util
import random
import time
from pathlib import Path

from vibe_sdk import DIRECTION_DELTAS, Action

SIZE = 12
MAX_TURNS = 40
OVERTIME_TURN = 32
MAX_HEALTH = 70
MAX_ENERGY = 50
HOLD = 4
VISION = 3
SCAN_VISION = 6
RESPAWN_TURNS = 3
PROTECTION_TURNS = 2
DECIDE_LIMIT_MS = 200
MAX_FAILURES = 3
COSTS = {"move": 1, "attack": 5, "shoot": 6, "collect": 2, "defend": 2, "scan": 8, "ability": 10, "use_item": 4}
ATTACK_RANGE = 1
SHOT_RANGE = 4

CORNERS = [(0, 0), (11, 0), (0, 11), (11, 11)]
CENTRE = [(5, 5), (6, 5), (5, 6), (6, 6)]
PADS = [(5, 0), (11, 5), (6, 11), (0, 6)]
POCKETS = {(x, y) for x in (0, 1, 10, 11) for y in (0, 1, 10, 11)}
RESERVED = set(CENTRE) | set(PADS) | POCKETS

CORE_SPAWN_TURN = 8
CORE_CARRY_TURNS = 3
CORE_RESPAWN_TURNS = 4
CORE_DEFUSE_TURNS = 2
RESOURCE_WAVE_EVERY = 8
RESOURCE_VALUE = 10
KILL_POINTS = 40
FIRST_BLOOD_POINTS = 20
CROWN_KILL_POINTS = 30
UPLINK_POINTS = 60
DEFUSE_POINTS = 40


def inside(x, y):
    return 0 <= x < SIZE and 0 <= y < SIZE


def cheb(a, b):
    return max(abs(a[0] - b[0]), abs(a[1] - b[1]))


def rotations(p):
    out = [p]
    for _ in range(3):
        x, y = out[-1]
        out.append((SIZE - 1 - y, x))
    return out


def generate_walls(rng):
    walls = set()
    for x in range(6):
        for y in range(6):
            orbit = rotations((x, y))
            if any(p in RESERVED for p in orbit):
                continue
            if rng.random() < 0.18:
                walls.update(orbit)
    return walls


def corner_cut(walls, a, b):
    dx, dy = b[0] - a[0], b[1] - a[1]
    return bool(dx and dy and (a[0] + dx, a[1]) in walls and (a[0], a[1] + dy) in walls)


def step_ok(walls, a, b):
    return inside(*b) and b not in walls and not corner_cut(walls, a, b)


def line_cells(a, b):
    x0, y0 = a
    x1, y1 = b
    dx, dy = abs(x1 - x0), -abs(y1 - y0)
    sx = 1 if x0 < x1 else -1
    sy = 1 if y0 < y1 else -1
    err = dx + dy
    cells = []
    while True:
        cells.append((x0, y0))
        if (x0, y0) == (x1, y1):
            return cells
        e2 = 2 * err
        if e2 >= dy:
            err += dy
            x0 += sx
        if e2 <= dx:
            err += dx
            y0 += sy


def line_clear(walls, a, b):
    path = line_cells(a, b)
    for prev, cur in zip(path, path[1:]):
        if cur != b and cur in walls:
            return False
        if corner_cut(walls, prev, cur):
            return False
    return True


def describe(act):
    if act.kind in ("move", "shoot"):
        return f"{act.kind.upper()} {act.direction}"
    if act.kind == "attack":
        return f"ATTACK {act.target}"
    return act.kind.upper()


class BotSlot:
    def __init__(self, index, name, bot, base):
        self.id = index
        self.name = name
        self.bot = bot
        self.base = base
        self.x, self.y = base
        self.health = MAX_HEALTH
        self.energy = MAX_ENERGY
        self.alive = True
        self.respawn_turn = 0
        self.hold = 0
        self.carrying_core = False
        self.score = 0
        self.kills = 0
        self.deaths = 0
        self.streak = 0
        self.banked = 0
        self.protected_until = -1
        self.scan_ready = False
        self.scan_active = False
        self.defended = False
        self.failures = 0
        self.disabled = False
        self.illegal = 0
        self.bad_turns = 0
        self.max_decide_ms = 0.0

    @property
    def pos(self):
        return (self.x, self.y)


class Match:
    def __init__(self, bots, seed):
        self.seed = seed
        self.rng = random.Random(seed)
        self.walls = generate_walls(self.rng)
        self.resources = {}
        self.add_resource_wave()
        self.slots = []
        for i, bot in enumerate(bots):
            base = CORNERS[(i + seed) % 4]
            self.slots.append(BotSlot(i, "YOU" if i == 0 else f"BOT{i}", bot, base))
        self.core = {"state": "absent", "pos": None, "carrier": None, "planter": None,
                     "plant_turn": 0, "defuse_count": 0, "respawn_turn": 0}
        self.turn = 0
        self.crown_id = None
        self.rank = {}
        self.first_blood = False
        self.events = []
        self.outcomes = {}
        self.damage_by = {}
        self.log = []

    def run(self):
        for t in range(1, MAX_TURNS + 1):
            self.turn = t
            self.events = []
            self.outcomes = {}
            self.start_turn()
            legal = self.collect_actions()
            self.resolve(legal)
            self.log.append({
                "turn": t,
                "outcomes": self.outcomes,
                "events": self.events,
                "states": {s.id: (s.health, s.energy, s.score, s.alive) for s in self.slots},
            })
        return self.results()

    def multiplier(self):
        return 2 if self.turn >= OVERTIME_TURN else 1

    def add_resource_wave(self):
        options = []
        for x in range(6):
            for y in range(6):
                orbit = rotations((x, y))
                if any(p in RESERVED or p in self.walls or p in self.resources for p in orbit):
                    continue
                options.append(orbit)
        for p in self.rng.choice(options):
            self.resources[p] = self.resources.get(p, 0) + 1

    def ranking(self):
        return sorted(self.slots, key=lambda s: (-s.score, -s.kills, s.deaths, -s.banked, s.id))

    def start_turn(self):
        t = self.turn
        if t == CORE_SPAWN_TURN:
            self.core.update(state="ground", pos=self.rng.choice(CENTRE))
            self.events.append("The Core appeared in the centre")
        elif self.core["state"] == "respawning" and t >= self.core["respawn_turn"]:
            self.core.update(state="ground", pos=self.rng.choice(CENTRE))
            self.events.append("The Core returned to the centre")
        if t > 1 and (t - 1) % RESOURCE_WAVE_EVERY == 0:
            self.add_resource_wave()
            self.events.append("Supply wave: 4 more resources dropped")
        regen = 10 if t >= OVERTIME_TURN else 5
        for s in self.slots:
            if not s.alive and t >= s.respawn_turn:
                s.alive = True
                s.health = MAX_HEALTH
                s.energy = MAX_ENERGY
                s.x, s.y = s.base
                s.protected_until = t + PROTECTION_TURNS - 1
                self.events.append(f"{s.name} respawned at base")
            elif s.alive:
                s.energy = min(MAX_ENERGY, s.energy + regen)
            s.scan_active, s.scan_ready = s.scan_ready, False
            s.defended = False
        self.rank = {s.id: place for place, s in enumerate(self.ranking(), start=1)}
        top = max(s.score for s in self.slots)
        leaders = [s for s in self.slots if s.score == top]
        self.crown_id = leaders[0].id if top > 0 and len(leaders) == 1 else None

    def is_marked(self, s):
        return (s.id == self.crown_id or s.carrying_core
                or (self.core["state"] == "planted" and self.core["planter"] == s.id))

    def core_pos(self):
        c = self.core
        if c["state"] == "carried":
            return self.slots[c["carrier"]].pos
        if c["state"] in ("ground", "planted"):
            return c["pos"]
        return None

    def visible_cells(self, origin, vision):
        seen = set()
        for x in range(SIZE):
            for y in range(SIZE):
                if cheb(origin, (x, y)) <= vision and line_clear(self.walls, origin, (x, y)):
                    seen.add((x, y))
        return seen

    def build_view(self, s):
        t = self.turn
        vision = SCAN_VISION if s.scan_active else VISION
        seen = self.visible_cells(s.pos, vision)
        enemies = []
        for o in self.slots:
            if o.id == s.id or not o.alive:
                continue
            marked = self.is_marked(o)
            if marked or o.pos in seen:
                enemies.append({"id": o.id, "x": o.x, "y": o.y, "health": max(o.health, 0),
                                "marked": marked, "carrying_core": o.carrying_core})
        core_at = self.core_pos()
        return {
            "self": {
                "id": s.id, "x": s.x, "y": s.y,
                "health": s.health, "max_health": MAX_HEALTH,
                "energy": s.energy, "max_energy": MAX_ENERGY,
                "cargo": s.hold, "cargo_capacity": HOLD,
                "score": s.score, "rank": self.rank[s.id], "streak": s.streak,
                "vision": vision, "spawn_protected": s.protected_until >= t,
                "carrying_core": s.carrying_core,
                "base": {"x": s.base[0], "y": s.base[1]},
            },
            "visible_enemies": enemies,
            "visible_resources": [{"x": x, "y": y, "count": n}
                                  for (x, y), n in sorted(self.resources.items()) if (x, y) in seen],
            "walls": [{"x": x, "y": y} for x, y in sorted(self.walls)],
            "uplinks": [{"x": x, "y": y} for x, y in PADS],
            "core": {"state": self.core["state"],
                     "x": core_at[0] if core_at else None,
                     "y": core_at[1] if core_at else None},
            "board": {"width": SIZE, "height": SIZE, "turn": t, "max_turns": MAX_TURNS,
                      "overtime": t >= OVERTIME_TURN},
        }

    def collect_actions(self):
        legal = {}
        for s in self.slots:
            if not s.alive:
                self.outcomes[s.id] = "waiting to respawn"
                continue
            if s.disabled:
                self.outcomes[s.id] = "switched off"
                continue
            view = self.build_view(s)
            started = time.perf_counter()
            act, error = None, None
            try:
                act = s.bot.decide(view)
            except Exception as exc:
                error = f"crashed ({type(exc).__name__}: {exc})"
            elapsed = (time.perf_counter() - started) * 1000
            s.max_decide_ms = max(s.max_decide_ms, elapsed)
            if error is None and elapsed > DECIDE_LIMIT_MS:
                error = f"too slow ({elapsed:.0f} ms)"
            elif error is None and not isinstance(act, Action):
                error = "returned something other than an Action"
            if error:
                self.fail(s, error)
                continue
            problem = self.check_legal(s, act)
            if problem:
                self.fail(s, f"{describe(act)} -> ILLEGAL: {problem}", illegal=True)
                continue
            s.failures = 0
            s.energy -= COSTS[act.kind]
            if act.kind in ("attack", "shoot", "collect"):
                s.protected_until = -1
            legal[s.id] = act
            self.outcomes[s.id] = describe(act)
        return legal

    def check_legal(self, s, act):
        kind = act.kind
        if kind in ("ability", "use_item"):
            return "abilities and items are not in the practice simulator yet"
        if s.energy < COSTS[kind]:
            return f"not enough energy ({s.energy} < {COSTS[kind]})"
        if kind in ("move", "shoot") and not (isinstance(act.direction, str) and act.direction in DIRECTION_DELTAS):
            return f"unknown direction {act.direction!r}"
        if kind == "move":
            dx, dy = DIRECTION_DELTAS[act.direction]
            if not inside(s.x + dx, s.y + dy):
                return "move off the board"
        if kind == "attack":
            target = self.slot_or_none(act.target)
            if target is None or not target.alive or target.id == s.id:
                return "no such enemy"
            if cheb(s.pos, target.pos) > ATTACK_RANGE:
                return "target too far away"
        if kind == "collect" and not self.can_collect(s):
            return "nothing to collect here"
        return None

    def can_collect(self, s):
        if self.core["state"] == "ground" and self.core["pos"] == s.pos:
            return True
        return self.resources.get(s.pos, 0) > 0 and s.hold < HOLD

    def slot_or_none(self, slot_id):
        if isinstance(slot_id, int) and 0 <= slot_id < len(self.slots):
            return self.slots[slot_id]
        return None

    def bot_at(self, pos):
        for s in self.slots:
            if s.alive and s.pos == pos:
                return s
        return None

    def shot_target(self, s, direction):
        dx, dy = DIRECTION_DELTAS[direction]
        x, y = s.x, s.y
        for _ in range(SHOT_RANGE):
            nxt = (x + dx, y + dy)
            if not step_ok(self.walls, (x, y), nxt):
                return None
            occupant = self.bot_at(nxt)
            if occupant:
                return occupant
            x, y = nxt
        return None

    def fail(self, s, text, illegal=False):
        self.outcomes[s.id] = text
        s.bad_turns += 1
        s.failures += 1
        if illegal:
            s.illegal += 1
        if s.failures >= MAX_FAILURES and not s.disabled:
            s.disabled = True
            self.events.append(f"{s.name} switched off after {MAX_FAILURES} failures in a row")

    def note(self, s, text):
        prev = self.outcomes.get(s.id)
        self.outcomes[s.id] = f"{prev} -> {text}" if prev else text

    def resolve(self, legal):
        t = self.turn
        mult = self.multiplier()
        alive = [s for s in self.slots if s.alive]
        self.damage_by = {}
        moved = set()

        for s in alive:
            act = legal.get(s.id)
            if act is None:
                continue
            if act.kind == "defend":
                s.defended = True
            elif act.kind == "scan":
                s.scan_ready = True

        occupied = {s.pos for s in alive}
        wants = {}
        for s in alive:
            act = legal.get(s.id)
            if act is None or act.kind != "move":
                continue
            dx, dy = DIRECTION_DELTAS[act.direction]
            target = (s.x + dx, s.y + dy)
            if target in occupied or not step_ok(self.walls, s.pos, target):
                self.note(s, "blocked")
            else:
                wants.setdefault(target, []).append(s)
        for target, movers in wants.items():
            if len(movers) > 1:
                for s in movers:
                    self.note(s, "blocked (two bots moved to one cell)")
                continue
            s = movers[0]
            s.x, s.y = target
            moved.add(s.id)
            self.note(s, f"moved to {target}")

        for s in alive:
            act = legal.get(s.id)
            if act is None or act.kind != "collect":
                continue
            if self.core["state"] == "ground" and self.core["pos"] == s.pos:
                self.core.update(state="carried", carrier=s.id, pos=None)
                s.carrying_core = True
                self.note(s, "picked up the Core")
                self.events.append(f"{s.name} picked up the Core")
            elif self.resources.get(s.pos, 0) > 0 and s.hold < HOLD:
                take = min(self.resources[s.pos], HOLD - s.hold)
                s.hold += take
                self.resources[s.pos] -= take
                if self.resources[s.pos] == 0:
                    del self.resources[s.pos]
                self.note(s, f"collected {take}")
            else:
                self.note(s, "nothing left to collect")

        hits = []
        for s in alive:
            act = legal.get(s.id)
            if act is None:
                continue
            if act.kind == "attack":
                hits.append((s, self.slots[act.target], self.rng.randint(16, 24)))
            elif act.kind == "shoot":
                victim = self.shot_target(s, act.direction)
                if victim is None:
                    self.note(s, "hit nothing")
                else:
                    hits.append((s, victim, self.rng.randint(10, 14)))
        for attacker, victim, dmg in hits:
            if victim.protected_until >= t:
                self.note(attacker, f"{victim.name} is spawn-protected")
                continue
            if victim.defended:
                dmg //= 2
            victim.health -= dmg
            self.damage_by.setdefault(victim.id, set()).add(attacker.id)
            self.note(attacker, f"hit {victim.name} for {dmg}")

        for victim in [s for s in alive if s.health <= 0]:
            killers = sorted(self.damage_by.get(victim.id, set()))
            if killers:
                self.award_kill(victim, killers, mult)
            victim.alive = False
            victim.deaths += 1
            victim.streak = 0
            victim.respawn_turn = t + RESPAWN_TURNS
            if victim.hold:
                self.resources[victim.pos] = self.resources.get(victim.pos, 0) + victim.hold
                victim.hold = 0
            if victim.carrying_core:
                self.core.update(state="ground", pos=victim.pos, carrier=None)
                victim.carrying_core = False
            self.events.append(f"{victim.name} was knocked out at {victim.pos}")

        for s in self.slots:
            if s.alive and s.carrying_core and s.id in moved and s.pos in PADS:
                self.core.update(state="planted", pos=s.pos, carrier=None, planter=s.id,
                                 plant_turn=t, defuse_count=0)
                s.carrying_core = False
                self.note(s, "planted the Core")
                self.events.append(f"Core planted at {s.pos} by {s.name}")

        c = self.core
        if c["state"] == "planted" and c["plant_turn"] < t:
            near = [s for s in self.slots if s.alive and s.id != c["planter"] and cheb(s.pos, c["pos"]) <= 1]
            c["defuse_count"] = c["defuse_count"] + 1 if near else 0
            if c["defuse_count"] >= CORE_DEFUSE_TURNS:
                for s in near:
                    s.score += DEFUSE_POINTS * mult
                names = ", ".join(s.name for s in near)
                self.events.append(f"Core defused; {names} each +{DEFUSE_POINTS * mult}")
                self.respawn_core(t)
            elif t - c["plant_turn"] >= CORE_CARRY_TURNS:
                planter = self.slots[c["planter"]]
                planter.score += UPLINK_POINTS * mult
                self.events.append(f"Core uplinked by {planter.name} (+{UPLINK_POINTS * mult})")
                self.respawn_core(t)

        for s in self.slots:
            if s.alive and s.hold and s.pos == s.base:
                value = s.hold * RESOURCE_VALUE * mult
                s.score += value
                s.banked += value
                self.events.append(f"{s.name} banked {s.hold} resources (+{value})")
                s.hold = 0

    def award_kill(self, victim, killers, mult):
        if not self.first_blood:
            self.first_blood = True
            first = self.slots[killers[0]]
            first.score += FIRST_BLOOD_POINTS * mult
            self.events.append(f"First blood: {first.name} (+{FIRST_BLOOD_POINTS * mult})")
        names = []
        for kid in killers:
            k = self.slots[kid]
            points = KILL_POINTS + (CROWN_KILL_POINTS if victim.id == self.crown_id else 0)
            k.score += points * mult
            k.kills += 1
            k.streak += 1
            names.append(k.name)
        self.events.append(f"{victim.name} killed by {', '.join(names)}")

    def respawn_core(self, t):
        self.core.update(state="respawning", pos=None, carrier=None, planter=None,
                         respawn_turn=t + CORE_RESPAWN_TURNS)

    def results(self):
        rows = []
        for place, s in enumerate(self.ranking(), start=1):
            rows.append({"place": place, "id": s.id, "name": s.name, "score": s.score,
                         "kills": s.kills, "deaths": s.deaths, "banked": s.banked,
                         "illegal": s.illegal, "bad_turns": s.bad_turns,
                         "disabled": s.disabled, "max_decide_ms": s.max_decide_ms})
        return {"seed": self.seed, "rows": rows, "log": self.log}


def load_bot_class(path):
    path = Path(path).resolve()
    spec = importlib.util.spec_from_file_location("bot_" + str(abs(hash(str(path)))), path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.MyBot


def play_match(you_cls, opp_cls, seed):
    bots = [you_cls()] + [opp_cls() for _ in range(3)]
    return Match(bots, seed).run()
