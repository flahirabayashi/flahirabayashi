#!/usr/bin/env python3
"""Animated SVG of a cell crawling over a GitHub contribution graph.

The cell moves through the year like an amoeba and engulfs every day with
contributions (phagocytosis). After the cell leaves, the "colonies" grow
back and the loop starts again. Two files are written: a light and a dark
version, so the README can follow the viewer's GitHub theme.

Usage:
    python3 scripts/cell_animation.py --user USERNAME --out dist
    python3 scripts/cell_animation.py --input days.json --out dist   # offline test

The online mode reads the contribution calendar from the GitHub GraphQL API
and needs a token in the GITHUB_TOKEN environment variable. The token that
GitHub Actions creates for each run is enough.
"""

import argparse
import datetime as dt
import json
import math
import os
import random
import urllib.request

# ---------------------------------------------------------------- settings --

SQUARE = 10           # size of one day in the graph (px)
GAP = 3               # space between days (px)
PITCH = SQUARE + GAP
MARGIN_X = 28         # room for the cell to enter and leave
MARGIN_Y = 18
RADIUS = 12           # cell radius (px)

SPEED = 60.0          # crawling speed (px/s)
EAT_PAUSE = 0.35      # time spent engulfing one day (s)
WANDER_PAUSE = 0.15   # short stop while "sensing" an empty spot (s)
REGROW = 1.8          # time for the colonies to grow back at the end (s)
MIN_STOPS = 14        # with few contributions, the cell also explores empty spots
MAX_LOOP = 60.0       # longest loop allowed (s)

LEVELS = {"NONE": 0, "FIRST_QUARTILE": 1, "SECOND_QUARTILE": 2,
          "THIRD_QUARTILE": 3, "FOURTH_QUARTILE": 4}

THEMES = {
    "light": {
        "empty": "#ebedf0",
        "levels": ["#9be9a8", "#40c463", "#30a14e", "#216e39"],
        "cytoplasm": "#e9ddff", "cytoplasm_opacity": 0.9,
        "membrane": "#7c3aed", "nucleus": "#8b5cf6", "nucleolus": "#4c1d95",
        "granule": "#a78bfa", "vacuole": "#ffffff", "vacuole_stroke": "#a78bfa",
        "food": "#40c463",
    },
    "dark": {
        "empty": "#161b22",
        "levels": ["#0e4429", "#006d32", "#26a641", "#39d353"],
        "cytoplasm": "#7c3aed", "cytoplasm_opacity": 0.42,
        "membrane": "#c4b5fd", "nucleus": "#c4b5fd", "nucleolus": "#6d28d9",
        "granule": "#ddd6fe", "vacuole": "#ede9fe", "vacuole_stroke": "#c4b5fd",
        "food": "#39d353",
    },
}

QUERY = """
query($login: String!) {
  user(login: $login) {
    contributionsCollection {
      contributionCalendar {
        weeks { contributionDays { weekday contributionLevel } }
      }
    }
  }
}
"""


# -------------------------------------------------------------------- data --

def fetch_calendar(user, token):
    """Return a list of (week, weekday, level) from the GitHub GraphQL API."""
    body = json.dumps({"query": QUERY, "variables": {"login": user}}).encode()
    request = urllib.request.Request(
        "https://api.github.com/graphql", data=body,
        headers={"Authorization": f"bearer {token}",
                 "Content-Type": "application/json",
                 "User-Agent": "cell-animation"})
    with urllib.request.urlopen(request, timeout=30) as response:
        payload = json.load(response)
    if payload.get("errors"):
        raise SystemExit(f"GitHub API error: {payload['errors']}")
    weeks = (payload["data"]["user"]["contributionsCollection"]
             ["contributionCalendar"]["weeks"])
    days = []
    for w, week in enumerate(weeks):
        for day in week["contributionDays"]:
            days.append((w, day["weekday"], LEVELS[day["contributionLevel"]]))
    return days


def load_input(path):
    """Offline mode: a JSON list of {"date": "YYYY-MM-DD", "level": 0-4}."""
    with open(path) as f:
        items = json.load(f)
    dates = [dt.date.fromisoformat(i["date"]) for i in items]
    first = min(dates)
    first_sunday = first - dt.timedelta(days=(first.weekday() + 1) % 7)
    days = []
    for item, date in zip(items, dates):
        weekday = (date.weekday() + 1) % 7          # 0 = Sunday, like GitHub
        week = (date - first_sunday).days // 7
        days.append((week, weekday, int(item["level"])))
    return days


# ------------------------------------------------------------------- route --

def center(week, weekday):
    return (MARGIN_X + week * PITCH + SQUARE / 2,
            MARGIN_Y + weekday * PITCH + SQUARE / 2)


def build_route(days, seed):
    """Stops ordered through the year: active days are eaten, the rest explored."""
    active = [(w, d, lvl) for (w, d, lvl) in days if lvl > 0]
    stops = [{"week": w, "day": d, "level": lvl, "eat": True} for (w, d, lvl) in active]

    n_weeks = max(w for (w, _, _) in days) + 1
    missing = MIN_STOPS - len(stops)
    if missing > 0:
        rng = random.Random(seed)
        taken = {(s["week"], s["day"]) for s in stops}
        band = n_weeks / missing
        for i in range(missing):
            for _ in range(20):
                w = min(n_weeks - 1, int(i * band + rng.random() * band))
                d = rng.randrange(7)
                if (w, d) not in taken:
                    taken.add((w, d))
                    stops.append({"week": w, "day": d, "level": 0, "eat": False})
                    break

    # left to right through the year, zig-zagging inside each week
    stops.sort(key=lambda s: (s["week"], s["day"] if s["week"] % 2 == 0 else -s["day"]))
    for s in stops:
        s["x"], s["y"] = center(s["week"], s["day"])
    return stops, n_weeks


def schedule(stops, width):
    """Times for every stop, plus the loop length."""
    mid_y = MARGIN_Y + 3 * PITCH + SQUARE / 2
    start = (-2.4 * RADIUS, mid_y)
    end = (width + 2.4 * RADIUS, mid_y)

    points = [start] + [(s["x"], s["y"]) for s in stops] + [end]
    length = sum(math.dist(a, b) for a, b in zip(points, points[1:]))
    n_eat = sum(s["eat"] for s in stops)
    n_wander = len(stops) - n_eat

    speed, eat_pause = SPEED, EAT_PAUSE
    busy = n_eat * eat_pause + n_wander * WANDER_PAUSE + REGROW
    if length / speed + busy > MAX_LOOP:              # busy graphs: hurry up
        eat_pause = min(EAT_PAUSE, 0.25 * MAX_LOOP / max(n_eat, 1))
        busy = n_eat * eat_pause + n_wander * WANDER_PAUSE + REGROW
        speed = length / max(MAX_LOOP - busy, 1.0)

    t = 0.0
    position = start
    frames = [(0.0, start)]                           # (time, position)
    for s in stops:
        t += math.dist(position, (s["x"], s["y"])) / speed
        position = (s["x"], s["y"])
        s["t"] = t
        frames.append((t, position))
        t += eat_pause if s["eat"] else WANDER_PAUSE
        s["pause"] = eat_pause if s["eat"] else WANDER_PAUSE
        frames.append((t, position))
    t += math.dist(position, end) / speed
    frames.append((t, end))
    leave = t
    total = t + REGROW
    return frames, leave, total


# ------------------------------------------------------------------ shapes --

def blob(rng, points=10):
    """A smooth, slightly irregular closed outline around (0, 0)."""
    phases = [rng.uniform(0, 2 * math.pi) for _ in range(3)]
    amps = [0.09, 0.07, 0.04]
    pts = []
    for i in range(points):
        a = 2 * math.pi * i / points
        r = RADIUS * (1 + amps[0] * math.sin(2 * a + phases[0])
                      + amps[1] * math.sin(3 * a + phases[1])
                      + amps[2] * math.sin(5 * a + phases[2]))
        pts.append((r * math.cos(a), r * math.sin(a)))
    # Catmull-Rom spline converted to cubic Bezier curves
    d = f"M{pts[0][0]:.2f},{pts[0][1]:.2f}"
    for i in range(points):
        p0, p1, p2, p3 = (pts[(i - 1) % points], pts[i],
                          pts[(i + 1) % points], pts[(i + 2) % points])
        c1 = (p1[0] + (p2[0] - p0[0]) / 6, p1[1] + (p2[1] - p0[1]) / 6)
        c2 = (p2[0] - (p3[0] - p1[0]) / 6, p2[1] - (p3[1] - p1[1]) / 6)
        d += (f" C{c1[0]:.2f},{c1[1]:.2f} {c2[0]:.2f},{c2[1]:.2f}"
              f" {p2[0]:.2f},{p2[1]:.2f}")
    return d + "Z"


def pct(t, total):
    return f"{100 * t / total:.3f}%"


# ------------------------------------------------------------------ render --

def render(days, stops, n_weeks, theme_name, seed):
    th = THEMES[theme_name]
    width = 2 * MARGIN_X + n_weeks * PITCH - GAP
    height = 2 * MARGIN_Y + 7 * PITCH - GAP
    frames, leave, total = schedule(stops, width)
    rng = random.Random(seed)
    css = []

    # cell movement: ease in and out of every stop, like a crawling amoeba
    rows = []
    last = None
    for t, (x, y) in frames:
        p = pct(t, total)
        if p == last:
            continue
        last = p
        rows.append(f"{p}{{transform:translate({x:.2f}px,{y:.2f}px);"
                    f"animation-timing-function:ease-in-out}}")
    x, y = frames[-1][1]
    rows.append(f"100%{{transform:translate({x:.2f}px,{y:.2f}px)}}")
    css.append("@keyframes move{" + "".join(rows) + "}")
    css.append(f"#cell{{animation:move {total:.2f}s infinite}}")

    eaten = [s for s in stops if s["eat"]]

    # engulfed days shrink away, then grow back after the cell leaves
    for i, s in enumerate(eaten):
        t_in = s["t"] - 0.05
        t_out = s["t"] + 0.7 * s["pause"]
        regrow = leave + rng.uniform(0.1, 0.65) * (total - leave)
        css.append(
            f"@keyframes e{i}{{0%,{pct(t_in, total)}{{transform:scale(1);opacity:1}}"
            f"{pct(t_out, total)},{pct(regrow, total)}{{transform:scale(0);opacity:0}}"
            f"100%{{transform:scale(1);opacity:1}}}}"
            f".e{i}{{animation:e{i} {total:.2f}s linear infinite}}")

    # a small "gulp" of the whole cell at every meal
    if 0 < len(eaten) <= 150:
        rows = ["0%{transform:scale(1)}"]
        busy_until = 0.0
        for s in eaten:
            a, b, c = s["t"] - 0.04, s["t"] + 0.10, s["t"] + 0.30
            if a <= busy_until + 0.02 or c >= total:
                continue
            rows.append(f"{pct(a, total)}{{transform:scale(1)}}"
                        f"{pct(b, total)}{{transform:scale(1.16,1.1)}}"
                        f"{pct(c, total)}{{transform:scale(1)}}")
            busy_until = c
        rows.append("100%{transform:scale(1)}")
        css.append("@keyframes gulp{" + "".join(rows) + "}")
        css.append(f"#body{{animation:gulp {total:.2f}s linear infinite}}")

    # food vacuoles: green vesicles that appear inside the cell and fade away
    pool = 4
    vesicles = []
    for k in range(pool):
        mine = [s for j, s in enumerate(eaten) if j % pool == k]
        if not mine:
            continue
        rows = ["0%{opacity:0;transform:scale(.3)}"]
        for j, s in enumerate(mine):
            start, peak = s["t"], s["t"] + 0.2
            stop = s["t"] + 1.8
            if j + 1 < len(mine):
                stop = min(stop, mine[j + 1]["t"] - 0.01)
            stop = min(stop, total - 0.01)
            if peak >= stop:
                continue
            rows.append(f"{pct(start, total)}{{opacity:0;transform:scale(.3)}}"
                        f"{pct(peak, total)}{{opacity:.95;transform:scale(1)}}"
                        f"{pct(stop, total)}{{opacity:0;transform:scale(.35)}}")
        rows.append("100%{opacity:0;transform:scale(.3)}")
        css.append(f"@keyframes v{k}{{" + "".join(rows) + "}")
        css.append(f".v{k}{{animation:v{k} {total:.2f}s linear infinite}}")
        angle = rng.uniform(0, 2 * math.pi)
        dist = rng.uniform(3.0, 5.5)
        vesicles.append(f'<circle class="v{k}" cx="{dist * math.cos(angle):.2f}" '
                        f'cy="{dist * math.sin(angle):.2f}" r="2.2" fill="{th["food"]}" '
                        f'opacity="0"/>')

    css.append("rect.e,#body,#body circle{transform-box:fill-box;transform-origin:center}")

    # ---- SVG ----
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
           f'viewBox="0 0 {width} {height}" role="img" aria-labelledby="title">',
           '<title id="title">A cell crawling over the GitHub contribution graph '
           'and engulfing the days with contributions</title>',
           "<style>" + "".join(css) + "</style>"]

    # empty grid
    for (w, d, _) in days:
        x = MARGIN_X + w * PITCH
        y = MARGIN_Y + d * PITCH
        out.append(f'<rect x="{x}" y="{y}" width="{SQUARE}" height="{SQUARE}" '
                   f'rx="2" fill="{th["empty"]}"/>')
    # active days on top
    for i, s in enumerate(eaten):
        x = MARGIN_X + s["week"] * PITCH
        y = MARGIN_Y + s["day"] * PITCH
        out.append(f'<rect class="e e{i}" x="{x}" y="{y}" width="{SQUARE}" '
                   f'height="{SQUARE}" rx="2" fill="{th["levels"][s["level"] - 1]}"/>')

    # the cell
    shape_rng = random.Random(seed + "-shape")
    shapes = [blob(shape_rng) for _ in range(4)]
    values = ";".join(shapes + [shapes[0]])
    spline = ";".join(["0.45 0 0.55 1"] * 4)
    sx, sy = frames[0][1]
    out.append(f'<g id="cell" transform="translate({sx:.2f} {sy:.2f})"><g id="body">')
    out.append(f'<path d="{shapes[0]}" fill="{th["cytoplasm"]}" '
               f'fill-opacity="{th["cytoplasm_opacity"]}" stroke="{th["membrane"]}" '
               f'stroke-width="1.4"><animate attributeName="d" dur="3.2s" '
               f'repeatCount="indefinite" calcMode="spline" keyTimes="0;0.25;0.5;0.75;1" '
               f'keySplines="{spline}" values="{values}"/></path>')
    for _ in range(5):                                  # granules in the cytoplasm
        a = shape_rng.uniform(0, 2 * math.pi)
        r = shape_rng.uniform(2.5, 7.0)
        out.append(f'<circle cx="{r * math.cos(a):.2f}" cy="{r * math.sin(a):.2f}" '
                   f'r="{shape_rng.uniform(0.6, 1.0):.2f}" fill="{th["granule"]}" '
                   f'opacity=".8"/>')
    out.extend(vesicles)
    # contractile vacuole: fills slowly, then empties at once
    out.append(f'<circle cx="4.6" cy="3.4" r="1.2" fill="{th["vacuole"]}" '
               f'stroke="{th["vacuole_stroke"]}" stroke-width=".5" opacity=".85">'
               f'<animate attributeName="r" values="1;2.3;0.4;1" keyTimes="0;0.6;0.68;1" '
               f'dur="2.7s" repeatCount="indefinite"/></circle>')
    # nucleus with nucleolus, drifting a little
    out.append(f'<circle cx="-2.4" cy="-1.6" r="3.9" fill="{th["nucleus"]}" opacity=".9">'
               f'<animate attributeName="cx" values="-2.4;-1.6;-2.9;-2.4" dur="4.3s" '
               f'repeatCount="indefinite"/><animate attributeName="cy" '
               f'values="-1.6;-2.3;-1.1;-1.6" dur="5.1s" repeatCount="indefinite"/></circle>')
    out.append(f'<circle cx="-2.0" cy="-1.9" r="1.3" fill="{th["nucleolus"]}">'
               f'<animate attributeName="cx" values="-2.0;-1.2;-2.5;-2.0" dur="4.3s" '
               f'repeatCount="indefinite"/><animate attributeName="cy" '
               f'values="-1.9;-2.6;-1.4;-1.9" dur="5.1s" repeatCount="indefinite"/></circle>')
    out.append("</g></g></svg>")
    return "\n".join(out)


# -------------------------------------------------------------------- main --

def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--user", help="GitHub username")
    source.add_argument("--input", help="offline JSON file with dates and levels")
    parser.add_argument("--out", default="dist", help="output folder (default: dist)")
    args = parser.parse_args()

    if args.user:
        token = os.environ.get("GITHUB_TOKEN")
        if not token:
            raise SystemExit("Set the GITHUB_TOKEN environment variable.")
        days = fetch_calendar(args.user, token)
        seed = args.user
    else:
        days = load_input(args.input)
        seed = os.path.basename(args.input)

    stops, n_weeks = build_route(days, seed)
    os.makedirs(args.out, exist_ok=True)
    for theme, name in (("light", "cell.svg"), ("dark", "cell-dark.svg")):
        path = os.path.join(args.out, name)
        with open(path, "w") as f:
            f.write(render(days, [dict(s) for s in stops], n_weeks, theme, seed))
        print(f"wrote {path}")


if __name__ == "__main__":
    main()
