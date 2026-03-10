import calendar
import datetime
import html
import json
import os
import re
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


def get_contribution_days(user, token):
    end_date = datetime.datetime.now(datetime.timezone.utc).date()
    start_date = end_date - datetime.timedelta(days=365)

    query = """
    query($login: String!, $from: DateTime!, $to: DateTime!) {
      user(login: $login) {
        contributionsCollection(from: $from, to: $to) {
          contributionCalendar {
            totalContributions
            weeks {
              contributionDays {
                date
                contributionCount
              }
            }
          }
        }
      }
    }
    """
    variables = {
        "login": user,
        "from": f"{start_date.isoformat()}T00:00:00Z",
        "to": f"{end_date.isoformat()}T23:59:59Z",
    }

    data = fetch_graphql(query, variables, token)
    user_data = data.get("user") if data else None
    if not user_data:
        return [], 0

    calendar = user_data["contributionsCollection"]["contributionCalendar"]
    days = []
    for week in calendar.get("weeks", []):
        for item in week.get("contributionDays", []):
            days.append(
                {
                    "date": datetime.date.fromisoformat(item["date"]),
                    "count": int(item.get("contributionCount", 0)),
                }
            )
    days.sort(key=lambda x: x["date"])
    return days, int(calendar.get("totalContributions", 0))


def get_contribution_days_from_svg(user):
    end_date = datetime.date.today()
    start_date = end_date - datetime.timedelta(days=365)
    years = sorted({start_date.year, end_date.year})
    headers = {"User-Agent": "github-cards-generator"}

    day_map = {}
    for year in years:
        url = f"https://github.com/users/{user}/contributions?to={year}-12-31"
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req) as resp:
            text = resp.read().decode("utf-8")

        day_tags = re.findall(r"<td[^>]*ContributionCalendar-day[^>]*>", text)
        for tag in day_tags:
            date_match = re.search(r'data-date="([^"]+)"', tag)
            level_match = re.search(r'data-level="([^"]+)"', tag)
            if not date_match or not level_match:
                continue
            date_obj = datetime.date.fromisoformat(date_match.group(1))
            if date_obj < start_date or date_obj > end_date:
                continue
            level = int(level_match.group(1))
            day_map[date_obj] = {"date": date_obj, "count": 1 if level > 0 else 0}

    days = list(day_map.values())
    days.sort(key=lambda x: x["date"])
    total = sum(item["count"] for item in days)
    return days, total


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


def day_count(start_date, end_date):
    return (end_date - start_date).days + 1


def shift_months(date_obj, months):
    month_index = (date_obj.year * 12 + (date_obj.month - 1)) + months
    year = month_index // 12
    month = (month_index % 12) + 1
    day = min(date_obj.day, calendar.monthrange(year, month)[1])
    return datetime.date(year, month, day)


def build_activity_segments(days):
    if not days:
        return [], None, None, 0

    first_active_idx = next((i for i, item in enumerate(days) if item["count"] > 0), 0)
    span = days[first_active_idx:]
    start_date = span[0]["date"]
    end_date = span[-1]["date"]
    active_days = sum(1 for item in span if item["count"] > 0)

    segments = []
    seg_start = span[0]["date"]
    seg_active = span[0]["count"] > 0
    prev_date = span[0]["date"]
    for item in span[1:]:
        cur_date = item["date"]
        cur_active = item["count"] > 0
        if cur_active != seg_active:
            segments.append({"start": seg_start, "end": prev_date, "active": seg_active})
            seg_start = cur_date
            seg_active = cur_active
        prev_date = cur_date
    segments.append({"start": seg_start, "end": prev_date, "active": seg_active})

    return segments, start_date, end_date, active_days


def merge_short_rest_segments(segments, min_rest_days=7):
    if not segments:
        return []

    merged = []
    for seg in segments:
        cur = {"start": seg["start"], "end": seg["end"], "active": seg["active"]}
        if (not cur["active"]) and day_count(cur["start"], cur["end"]) < min_rest_days:
            cur["active"] = True

        if merged and merged[-1]["active"] == cur["active"]:
            merged[-1]["end"] = cur["end"]
        else:
            merged.append(cur)
    return merged


def render_activity_svg(user, days, updated):
    width = 960
    height = 250
    track_x = 72
    track_y = 108
    track_w = 816
    track_h = 30
    window_months = 6

    if days:
        cutoff = shift_months(days[-1]["date"], -window_months)
        days = [item for item in days if item["date"] >= cutoff]

    raw_segments, start_date, end_date, active_days = build_activity_segments(days)
    if not raw_segments:
        return "\n".join(
            [
                f'<svg width="{width}" height="{height}" viewBox="0 0 {width} {height}" xmlns="http://www.w3.org/2000/svg" role="img" aria-label="Activity map timeline">',
                "<rect x=\"0\" y=\"0\" width=\"960\" height=\"250\" rx=\"14\" fill=\"#0b1220\"/>",
                "<rect x=\"18\" y=\"16\" width=\"924\" height=\"218\" rx=\"10\" fill=\"#0f172a\" stroke=\"#1f2937\" stroke-width=\"1.5\"/>",
                "<text x=\"42\" y=\"45\" fill=\"#e5e7eb\" font-size=\"20\" font-family=\"Consolas, Courier New, monospace\" font-weight=\"700\">ACTIVITY MAP</text>",
                "<text x=\"42\" y=\"72\" fill=\"#94a3b8\" font-size=\"12\" font-family=\"Consolas, Courier New, monospace\">No contribution data available.</text>",
                "</svg>",
            ]
        )
    segments = merge_short_rest_segments(raw_segments, min_rest_days=7)

    total_days = day_count(start_date, end_date)
    active_ratio = (active_days / total_days) * 100.0 if total_days > 0 else 0.0
    window_contributions = sum(item["count"] for item in days)

    def x_for_start(date_obj):
        offset = (date_obj - start_date).days
        return track_x + int(round(track_w * (offset / total_days)))

    def x_for_end(date_obj):
        offset = (date_obj - start_date).days + 1
        return track_x + int(round(track_w * (offset / total_days)))

    lines = [
        f'<svg width="{width}" height="{height}" viewBox="0 0 {width} {height}" xmlns="http://www.w3.org/2000/svg" role="img" aria-label="Activity map timeline">',
        "<defs>",
        '<linearGradient id="bg" x1="0" y1="0" x2="1" y2="1">',
        '<stop offset="0%" stop-color="#0b1220"/>',
        '<stop offset="100%" stop-color="#111827"/>',
        "</linearGradient>",
        '<linearGradient id="dev" x1="0" y1="0" x2="1" y2="0">',
        '<stop offset="0%" stop-color="#22d3ee"/>',
        '<stop offset="100%" stop-color="#38bdf8"/>',
        "</linearGradient>",
        "<style>",
        '.title { fill: #e5e7eb; font: 700 20px "Consolas", "Courier New", monospace; letter-spacing: 1px; }',
        '.sub { fill: #94a3b8; font: 11px "Consolas", "Courier New", monospace; }',
        '.label { fill: #dbeafe; font: 600 11px "Consolas", "Courier New", monospace; }',
        '.tick { fill: #94a3b8; font: 10px "Consolas", "Courier New", monospace; }',
        '.devText { fill: #0b1220; font: 700 10px "Consolas", "Courier New", monospace; }',
        '.restText { fill: #f1f5f9; font: 700 10px "Consolas", "Courier New", monospace; }',
        ".track { fill: #1f2937; }",
        ".rest { fill: #475569; }",
        "</style>",
        "</defs>",
        '<rect x="0" y="0" width="960" height="250" rx="14" fill="url(#bg)"/>',
        '<rect x="18" y="16" width="924" height="218" rx="10" fill="#0f172a" stroke="#1f2937" stroke-width="1.5"/>',
        '<text class="title" x="42" y="45">ACTIVITY MAP</text>',
        '<text class="sub" x="42" y="64">Based on GitHub contribution graph</text>',
        f'<text class="sub" x="680" y="45">UPDATED {esc(updated)}</text>',
        f'<text class="sub" x="610" y="64">LAST {window_months}M UNITS {window_contributions} / ACTIVE {active_days} ({active_ratio:.1f}%)</text>',
        f'<rect class="track" x="{track_x}" y="{track_y}" width="{track_w}" height="{track_h}" rx="15"/>',
    ]

    for seg in segments:
        x0 = x_for_start(seg["start"])
        x1 = x_for_end(seg["end"])
        if seg == segments[-1]:
            x1 = track_x + track_w
        seg_w = max(2, x1 - x0)
        fill = "url(#dev)" if seg["active"] else "#475569"
        lines.append(
            f'<rect x="{x0}" y="{track_y}" width="{seg_w}" height="{track_h}" rx="15" fill="{fill}"/>'
        )
        if seg_w >= 48:
            text_class = "devText" if seg["active"] else "restText"
            text_value = "DEV" if seg["active"] else "REST"
            text_x = x0 + int(seg_w / 2)
            lines.append(f'<text class="{text_class}" x="{text_x}" y="{track_y + 19}" text-anchor="middle">{text_value}</text>')

    boundary_dates = [start_date] + [seg["start"] for seg in segments[1:]] + [end_date]
    last_label_x = -10_000
    for idx, date_obj in enumerate(boundary_dates):
        x = x_for_start(date_obj) if idx < len(boundary_dates) - 1 else x_for_end(date_obj)
        if idx not in (0, len(boundary_dates) - 1) and x - last_label_x < 78:
            continue
        lines.append(f'<line x1="{x}" y1="{track_y + 36}" x2="{x}" y2="{track_y + 50}" stroke="#64748b" stroke-width="1"/>')
        label = "NOW" if idx == len(boundary_dates) - 1 else date_obj.isoformat()
        lines.append(f'<text class="tick" x="{x}" y="{track_y + 65}" text-anchor="middle">{esc(label)}</text>')
        last_label_x = x

    preview = segments if len(segments) <= 3 else segments[:2] + segments[-1:]
    y = 204
    for idx, seg in enumerate(preview):
        end_label = "NOW" if idx == len(preview) - 1 and seg == segments[-1] else seg["end"].isoformat()
        state = "DEV" if seg["active"] else "REST"
        text = f'{seg["start"].isoformat()} ~ {end_label} {state}'
        lines.append(f'<text class="label" x="72" y="{y}">{esc(text)}</text>')
        y += 18

    lines.append(f'<text class="label" x="560" y="222">@{esc(user)} contribution timeline</text>')
    lines.append("</svg>")
    return "\n".join(lines)


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
    contribution_days = []
    try:
        if token:
            contribution_days, _ = get_contribution_days(user, token)
        if not contribution_days:
            contribution_days, _ = get_contribution_days_from_svg(user)
    except Exception as exc:
        print(f"Warning: failed to fetch contribution graph: {exc}")

    out_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "profile"))
    os.makedirs(out_dir, exist_ok=True)
    stats_svg = render_stats_svg(stats, updated)
    langs_svg = render_langs_svg(langs, updated)
    activity_svg = render_activity_svg(user, contribution_days, updated)

    with open(os.path.join(out_dir, "github-stats.svg"), "w", encoding="utf-8") as f:
        f.write(stats_svg)
    with open(os.path.join(out_dir, "top-langs.svg"), "w", encoding="utf-8") as f:
        f.write(langs_svg)
    with open(os.path.join(out_dir, "self-reported-activity.svg"), "w", encoding="utf-8") as f:
        f.write(activity_svg)


if __name__ == "__main__":
    main()
