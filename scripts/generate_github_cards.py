import datetime
import html
import json
import os
import urllib.request


API_BASE = "https://api.github.com"
DEFAULT_USER = "JWookLe"


def fetch_json(url, token):
    headers = {"User-Agent": "github-cards-generator"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    return data


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

    out_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "profile"))
    os.makedirs(out_dir, exist_ok=True)
    stats_svg = render_stats_svg(stats, updated)
    langs_svg = render_langs_svg(langs, updated)

    with open(os.path.join(out_dir, "github-stats.svg"), "w", encoding="utf-8") as f:
        f.write(stats_svg)
    with open(os.path.join(out_dir, "top-langs.svg"), "w", encoding="utf-8") as f:
        f.write(langs_svg)


if __name__ == "__main__":
    main()
