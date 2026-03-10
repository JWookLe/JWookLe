import datetime
import html
import json
import os
import urllib.request


API_BASE = "https://api.github.com"
GRAPHQL_API = "https://api.github.com/graphql"
DEFAULT_USER = "JWookLe"


def fetch_json(url, token):
    headers = {"User-Agent": "github-cards-generator"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    return data


def fetch_graphql(query, variables, token):
    if not token:
        raise RuntimeError("Missing GitHub token for GraphQL request")

    headers = {
        "User-Agent": "github-cards-generator",
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    payload = json.dumps({"query": query, "variables": variables}).encode("utf-8")
    req = urllib.request.Request(GRAPHQL_API, data=payload, headers=headers)
    with urllib.request.urlopen(req) as resp:
        data = json.loads(resp.read().decode("utf-8"))

    if data.get("errors"):
        raise RuntimeError(data["errors"][0].get("message", "GraphQL request failed"))
    return data.get("data") or {}


def get_user(user, token):
    return fetch_json(f"{API_BASE}/users/{user}", token)


def get_repos(user, token):
    repos = []
    page = 1
    while True:
        url = f"{API_BASE}/users/{user}/repos?per_page=100&page={page}"
        data = fetch_json(url, token)
        if not data:
            break
        repos.extend(data)
        if len(data) < 100:
            break
        page += 1
    return repos


def get_contribution_calendar(user, token):
    end_dt = datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0)
    start_dt = end_dt - datetime.timedelta(days=365)

    query = """
    query($login: String!, $from: DateTime!, $to: DateTime!) {
      user(login: $login) {
        contributionsCollection(from: $from, to: $to) {
          contributionCalendar {
            totalContributions
            weeks {
              firstDay
              contributionDays {
                date
                contributionCount
                contributionLevel
              }
            }
          }
        }
      }
    }
    """
    variables = {
        "login": user,
        "from": start_dt.isoformat().replace("+00:00", "Z"),
        "to": end_dt.isoformat().replace("+00:00", "Z"),
    }
    data = fetch_graphql(query, variables, token)
    user_data = data.get("user") if data else None
    if not user_data:
        return None
    return user_data["contributionsCollection"]["contributionCalendar"]


def compute_language_sizes(repos):
    lang_sizes = {}
    total_size = 0
    for repo in repos:
        lang = repo.get("language")
        size = repo.get("size") or 0
        if not lang or size <= 0:
            continue
        lang_sizes[lang] = lang_sizes.get(lang, 0) + size
        total_size += size
    if total_size <= 0:
        return []
    items = sorted(lang_sizes.items(), key=lambda x: x[1], reverse=True)
    top = items[:5]
    return [(lang, size, size / total_size * 100.0) for lang, size in top]


def esc(value):
    return html.escape(str(value))


def build_month_labels(weeks):
    labels = []
    seen = set()
    for idx, week in enumerate(weeks):
        first_day = week.get("firstDay")
        if not first_day:
            continue
        day = datetime.date.fromisoformat(first_day)
        marker = (day.year, day.month)
        if marker in seen:
            continue
        seen.add(marker)
        labels.append((idx, day.strftime("%b %Y")))
    return labels


def render_activity_svg(user, calendar, updated):
    width = 960
    height = 220
    grid_x = 185
    grid_y = 68
    cell = 10
    gap = 3
    step = cell + gap
    days_in_week = 7
    color_map = {
        "NONE": "#1f2937",
        "FIRST_QUARTILE": "#155e75",
        "SECOND_QUARTILE": "#0e7490",
        "THIRD_QUARTILE": "#06b6d4",
        "FOURTH_QUARTILE": "#67e8f9",
    }

    weeks = []
    total = 0
    if calendar:
        weeks = calendar.get("weeks", [])
        total = calendar.get("totalContributions", 0)

    grid_width = max(1, len(weeks)) * step - gap
    grid_height = days_in_week * step - gap
    month_labels = build_month_labels(weeks)

    svg = [
        f'<svg width="{width}" height="{height}" viewBox="0 0 {width} {height}" xmlns="http://www.w3.org/2000/svg">',
        "<defs>",
        '<linearGradient id="bgGradient" x1="0" y1="0" x2="1" y2="1">',
        '<stop offset="0%" stop-color="#0b1220"/>',
        '<stop offset="100%" stop-color="#111827"/>',
        "</linearGradient>",
        '<pattern id="gridPattern" width="40" height="40" patternUnits="userSpaceOnUse">',
        '<path d="M 40 0 L 0 0 0 40" fill="none" stroke="#1f2937" stroke-width="1"/>',
        "</pattern>",
        "<style>",
        '.bg { fill: url(#bgGradient); }',
        '.grid { fill: url(#gridPattern); opacity: 0.35; }',
        '.panel { fill: #0f172a; stroke: #1f2937; stroke-width: 1.5; }',
        '.title { fill: #e5e7eb; font: 700 20px "Consolas", "Courier New", monospace; letter-spacing: 1px; }',
        '.subtitle { fill: #9ca3af; font: 11px "Consolas", "Courier New", monospace; }',
        '.hud { fill: #38bdf8; font: 700 12px "Consolas", "Courier New", monospace; }',
        '.label { fill: #cbd5f5; font: 11px "Consolas", "Courier New", monospace; }',
        '.weeklabel { fill: #94a3b8; font: 10px "Consolas", "Courier New", monospace; }',
        '.legend { fill: #e5e7eb; font: 11px "Consolas", "Courier New", monospace; }',
        '.note { fill: #94a3b8; font: 10px "Consolas", "Courier New", monospace; }',
        '.corner { fill: #22d3ee; }',
        "</style>",
        "</defs>",
        f'<rect class="bg" x="0" y="0" width="{width}" height="{height}" rx="14" />',
        f'<rect class="grid" x="0" y="0" width="{width}" height="{height}" rx="14" />',
        '<rect class="panel" x="18" y="16" width="924" height="188" rx="10" />',
        '<rect class="corner" x="30" y="28" width="8" height="8" />',
        '<rect class="corner" x="922" y="28" width="8" height="8" />',
        '<rect class="corner" x="30" y="182" width="8" height="8" />',
        '<rect class="corner" x="922" y="182" width="8" height="8" />',
        '<text class="title" x="44" y="48">ACTIVITY MAP</text>',
        '<text class="subtitle" x="44" y="68">GitHub contribution calendar (last 365 days)</text>',
        f'<text class="hud" x="730" y="48">TOTAL {total}</text>',
        f'<text class="hud" x="730" y="68">UPDATED {esc(updated)}</text>',
    ]

    if not weeks:
        svg.extend(
            [
                '<text class="legend" x="44" y="110">Unable to load activity data.</text>',
                '<text class="note" x="44" y="128">Check GitHub token permissions for GraphQL access.</text>',
            ]
        )
    else:
        svg.extend(
            [
                f'<rect x="{grid_x - 1}" y="{grid_y - 1}" width="{grid_width + 2}" height="{grid_height + 2}" rx="5" fill="#0b1220" stroke="#334155" />',
                f'<text class="weeklabel" x="{grid_x - 48}" y="{grid_y + cell}">Sun</text>',
                f'<text class="weeklabel" x="{grid_x - 48}" y="{grid_y + step * 2 + cell}">Tue</text>',
                f'<text class="weeklabel" x="{grid_x - 48}" y="{grid_y + step * 4 + cell}">Thu</text>',
                f'<text class="weeklabel" x="{grid_x - 48}" y="{grid_y + step * 6 + cell}">Sat</text>',
            ]
        )

        for week_idx, label in month_labels:
            x = grid_x + week_idx * step
            if x > 900:
                continue
            svg.append(f'<text class="label" x="{x}" y="{grid_y - 10}">{esc(label)}</text>')

        for week_idx, week in enumerate(weeks):
            days = week.get("contributionDays", [])
            for day_idx, day in enumerate(days):
                if day_idx >= days_in_week:
                    continue
                level = day.get("contributionLevel", "NONE")
                count = day.get("contributionCount", 0)
                color = color_map.get(level, color_map["NONE"])
                x = grid_x + week_idx * step
                y = grid_y + day_idx * step
                svg.append(
                    f'<rect x="{x}" y="{y}" width="{cell}" height="{cell}" rx="2" fill="{color}">'
                    f'<title>{esc(day.get("date"))}: {count} contributions</title></rect>'
                )

        legend_x = 670
        legend_y = 174
        svg.append('<text class="legend" x="614" y="184">Less</text>')
        for idx, color in enumerate(
            [
                color_map["NONE"],
                color_map["FIRST_QUARTILE"],
                color_map["SECOND_QUARTILE"],
                color_map["THIRD_QUARTILE"],
                color_map["FOURTH_QUARTILE"],
            ]
        ):
            x = legend_x + idx * 14
            svg.append(f'<rect x="{x}" y="{legend_y}" width="10" height="10" rx="2" fill="{color}" />')
        svg.append(f'<text class="legend" x="{legend_x + 78}" y="184">More</text>')

    svg.append(f'<text class="note" x="44" y="186">@{esc(user)} | auto-generated</text>')
    svg.append("</svg>")
    return "\n".join(svg)


def render_stats_svg(stats, updated):
    width = 495
    height = 165
    left_label_x = 20
    left_value_x = 150
    right_label_x = 270
    right_value_x = 400
    ys = [65, 90, 115]

    lines_left = [
        ("Public Repos", stats["public_repos"]),
        ("Total Stars", stats["stars"]),
        ("Total Forks", stats["forks"]),
    ]
    lines_right = [
        ("Followers", stats["followers"]),
        ("Following", stats["following"]),
        ("Updated", updated),
    ]

    svg = [
        f'<svg width="{width}" height="{height}" viewBox="0 0 {width} {height}" '
        'xmlns="http://www.w3.org/2000/svg" role="img" aria-label="GitHub stats">',
        '<rect x="0.5" y="0.5" width="494" height="164" rx="8" fill="#1a1b27" stroke="#30364a"/>',
        '<text x="20" y="30" fill="#c0caf5" font-size="18" font-family="Segoe UI, Arial, sans-serif">GitHub Stats</text>',
    ]

    for (label, value), y in zip(lines_left, ys):
        svg.append(
            f'<text x="{left_label_x}" y="{y}" fill="#a9b1d6" font-size="12" '
            'font-family="Segoe UI, Arial, sans-serif">'
            f"{esc(label)}</text>"
        )
        svg.append(
            f'<text x="{left_value_x}" y="{y}" fill="#7aa2f7" font-size="12" '
            'font-family="Segoe UI, Arial, sans-serif">'
            f"{esc(value)}</text>"
        )

    for (label, value), y in zip(lines_right, ys):
        svg.append(
            f'<text x="{right_label_x}" y="{y}" fill="#a9b1d6" font-size="12" '
            'font-family="Segoe UI, Arial, sans-serif">'
            f"{esc(label)}</text>"
        )
        svg.append(
            f'<text x="{right_value_x}" y="{y}" fill="#7aa2f7" font-size="12" '
            'font-family="Segoe UI, Arial, sans-serif">'
            f"{esc(value)}</text>"
        )

    svg.append(
        '<text x="20" y="150" fill="#565f89" font-size="10" '
        'font-family="Segoe UI, Arial, sans-serif">Static snapshot from GitHub API</text>'
    )
    svg.append("</svg>")
    return "\n".join(svg)


def render_langs_svg(langs, updated):
    width = 495
    height = 165
    bar_x = 170
    bar_max_width = 290
    bar_height = 8
    row_start = 60
    row_gap = 20

    svg = [
        f'<svg width="{width}" height="{height}" viewBox="0 0 {width} {height}" '
        'xmlns="http://www.w3.org/2000/svg" role="img" aria-label="Top languages">',
        '<rect x="0.5" y="0.5" width="494" height="164" rx="8" fill="#1a1b27" stroke="#30364a"/>',
        '<text x="20" y="30" fill="#c0caf5" font-size="18" font-family="Segoe UI, Arial, sans-serif">Top Languages</text>',
    ]

    if not langs:
        svg.append(
            '<text x="20" y="85" fill="#a9b1d6" font-size="12" font-family="Segoe UI, Arial, sans-serif">'
            "No language data available</text>"
        )
    else:
        for idx, (lang, _size, pct) in enumerate(langs):
            y = row_start + idx * row_gap
            bar_y = y - 7
            bar_width = int(bar_max_width * (pct / 100.0))
            svg.append(
                f'<text x="20" y="{y}" fill="#a9b1d6" font-size="12" font-family="Segoe UI, Arial, sans-serif">'
                f"{esc(lang)}</text>"
            )
            svg.append(
                f'<text x="120" y="{y}" fill="#7aa2f7" font-size="12" font-family="Segoe UI, Arial, sans-serif">'
                f"{pct:.1f}%</text>"
            )
            svg.append(
                f'<rect x="{bar_x}" y="{bar_y}" width="{bar_max_width}" height="{bar_height}" '
                'rx="4" fill="#2a2e3f"/>'
            )
            svg.append(
                f'<rect x="{bar_x}" y="{bar_y}" width="{bar_width}" height="{bar_height}" '
                'rx="4" fill="#9ece6a"/>'
            )

    svg.append(
        '<text x="20" y="150" fill="#565f89" font-size="10" '
        'font-family="Segoe UI, Arial, sans-serif">Static snapshot from GitHub API</text>'
    )
    svg.append("</svg>")
    return "\n".join(svg)


def main():
    user = os.environ.get("GITHUB_USER", DEFAULT_USER)
    token = os.environ.get("GITHUB_TOKEN", "")

    user_data = get_user(user, token)
    repos = get_repos(user, token)
    active_repos = [repo for repo in repos if not repo.get("fork") and not repo.get("archived")]

    stats = {
        "public_repos": user_data.get("public_repos", 0),
        "followers": user_data.get("followers", 0),
        "following": user_data.get("following", 0),
        "stars": sum(repo.get("stargazers_count", 0) for repo in active_repos),
        "forks": sum(repo.get("forks_count", 0) for repo in active_repos),
    }

    langs = compute_language_sizes(active_repos)
    updated = datetime.date.today().isoformat()
    activity_calendar = None
    try:
        activity_calendar = get_contribution_calendar(user, token)
    except Exception as exc:
        print(f"Warning: failed to fetch contribution calendar: {exc}")

    out_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "profile"))
    os.makedirs(out_dir, exist_ok=True)
    stats_svg = render_stats_svg(stats, updated)
    langs_svg = render_langs_svg(langs, updated)
    activity_svg = render_activity_svg(user, activity_calendar, updated) if activity_calendar else None

    with open(os.path.join(out_dir, "github-stats.svg"), "w", encoding="utf-8") as f:
        f.write(stats_svg)
    with open(os.path.join(out_dir, "top-langs.svg"), "w", encoding="utf-8") as f:
        f.write(langs_svg)
    if activity_svg is None:
        print("Warning: skipped activity map update because contribution calendar is unavailable")
    else:
        with open(os.path.join(out_dir, "self-reported-activity.svg"), "w", encoding="utf-8") as f:
            f.write(activity_svg)


if __name__ == "__main__":
    main()
