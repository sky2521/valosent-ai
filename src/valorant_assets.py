"""Official valorant-api.com asset caching + local tactical SVG fallbacks for all 30 agents & 13 maps."""

from __future__ import annotations

import html
import json
import logging
import re
import threading
import urllib.error
import urllib.request
from pathlib import Path

import pandas as pd

BASE_DIR = Path(__file__).resolve().parents[1]
CACHE_PATH = BASE_DIR / "data" / "valorant_assets_cache.json"
AGENT_ROLES_PATH = BASE_DIR / "data" / "agents" / "agent_roles.csv"
FALLBACK_DIR = BASE_DIR / "static" / "assets" / "fallbacks"
LOGGER = logging.getLogger(__name__)

VALORANT_AGENTS_API = "https://valorant-api.com/v1/agents?isPlayableCharacter=true"
VALORANT_MAPS_API = "https://valorant-api.com/v1/maps"

ALL_13_MAPS = (
    "Ascent", "Bind", "Breeze", "Fracture", "Haven", "Icebox",
    "Lotus", "Pearl", "Split", "Sunset", "Abyss", "Corrode", "Summit",
)

MAP_FALLBACK_META = {
    "Ascent":   {"coords": "45°26'BF'N,12°20'Q'E", "accent": "#4FA8D8", "bg": "#111E2B"},
    "Bind":     {"coords": "34°2'A'N,6°51'Z'W",   "accent": "#E6A14A", "bg": "#211913"},
    "Breeze":   {"coords": "26°11'AG'N,71°10'W",  "accent": "#3AC6B8", "bg": "#0E2124"},
    "Fracture": {"coords": "35°48'BI'N,106°08'W", "accent": "#D68249", "bg": "#1F1713"},
    "Haven":    {"coords": "27°28'A'N,89°38'W",   "accent": "#C95A5A", "bg": "#1F1518"},
    "Icebox":   {"coords": "76°44'A'N,149°30'E",  "accent": "#64B5F6", "bg": "#0F1D2B"},
    "Lotus":    {"coords": "14°07'AD'N,74°53'E",  "accent": "#B975E6", "bg": "#1C1426"},
    "Pearl":    {"coords": "38°42'ED'N,9°08'W",   "accent": "#4DA3D9", "bg": "#0F1A29"},
    "Split":    {"coords": "35°41'CD'N,139°41'E", "accent": "#58C4A8", "bg": "#112122"},
    "Sunset":   {"coords": "34°03'N,118°14'W",    "accent": "#FF6B5A", "bg": "#231419"},
    "Abyss":    {"coords": "70°16'N,68°51'W",     "accent": "#5A7CFF", "bg": "#101628"},
    "Corrode":  {"coords": "48°51'N,2°21'E",      "accent": "#5CE0A8", "bg": "#11221D"},
    "Summit":   {"coords": "27°59'N,86°55'E",     "accent": "#FF4655", "bg": "#18141E"},
}

ROLE_COLORS = {
    "Duelist":    "#FF4655",
    "Controller": "#59A5FF",
    "Initiator":  "#4CD4A9",
    "Sentinel":   "#EAB36B",
}

_ASSET_LOCK = threading.Lock()
_ASSET_CACHE: dict | None = None


def _slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(name).strip().lower()).strip("_")


def _norm(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", str(name).casefold())


def _write_fallback_svgs(agents_catalog: list[dict]) -> None:
    """Create crisp local VALORANT tactical SVG fallbacks so images never break offline."""
    FALLBACK_DIR.mkdir(parents=True, exist_ok=True)

    # Role emblem SVGs
    role_paths = {
        "Duelist":    "M32 6 L44 26 L58 32 L44 38 L32 58 L20 38 L6 32 L20 26 Z",
        "Controller": "M32 10 A22 22 0 1 0 32 54 A22 22 0 1 0 32 10 Z M32 22 A10 10 0 1 1 32 42 A10 10 0 1 1 32 22 Z",
        "Initiator":  "M12 18 L52 32 L12 46 L22 32 Z",
        "Sentinel":   "M32 8 L52 16 V34 C52 46 42 54 32 58 C22 54 12 46 12 34 V16 Z",
    }
    for role, path_d in role_paths.items():
        color = ROLE_COLORS[role]
        svg = (
            f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64">'
            f'<path d="{path_d}" fill="none" stroke="{color}" stroke-width="4" stroke-linejoin="miter"/>'
            f'<circle cx="32" cy="32" r="4" fill="{color}"/>'
            f'</svg>\n'
        )
        (FALLBACK_DIR / f"role_{_slug(role)}.svg").write_text(svg, encoding="utf-8")

    # Agent fallback icons & portraits
    for item in agents_catalog:
        agent = item["agent"]
        role = item["role"]
        slug = _slug(agent)
        accent = ROLE_COLORS.get(role, "#FF4655")
        initials = re.sub(r"[^A-Za-z]", "", agent)[:2].upper() or "AG"
        safe_name = html.escape(agent.upper())
        safe_role = html.escape(role.upper())

        icon_svg = f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 128 128">
  <defs>
    <linearGradient id="g_{slug}" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0%" stop-color="#192634"/>
      <stop offset="100%" stop-color="#0B1219"/>
    </linearGradient>
  </defs>
  <polygon points="0,0 112,0 128,16 128,128 16,128 0,112" fill="url(#g_{slug})" stroke="{accent}" stroke-width="3"/>
  <line x1="0" y1="96" x2="128" y2="96" stroke="{accent}" stroke-opacity="0.28" stroke-width="1"/>
  <text x="64" y="72" text-anchor="middle" font-family="Rajdhani, Segoe UI, Arial, sans-serif" font-size="48" font-weight="700" fill="#ECE8E1">{initials}</text>
  <text x="64" y="114" text-anchor="middle" font-family="Rajdhani, Segoe UI, Arial, sans-serif" font-size="13" font-weight="700" letter-spacing="2" fill="{accent}">{safe_role}</text>
</svg>
"""
        (FALLBACK_DIR / f"agent_{slug}_icon.svg").write_text(icon_svg, encoding="utf-8")

        portrait_svg = f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 600 800">
  <defs>
    <radialGradient id="p_{slug}" cx="55%" cy="35%" r="60%">
      <stop offset="0%" stop-color="{accent}" stop-opacity="0.34"/>
      <stop offset="65%" stop-color="#0F1923" stop-opacity="0.1"/>
      <stop offset="100%" stop-color="#0F1923" stop-opacity="0"/>
    </radialGradient>
  </defs>
  <rect width="600" height="800" fill="url(#p_{slug})"/>
  <path d="M210 180 L390 180 L430 260 L460 540 L410 780 L190 780 L140 540 L170 260 Z" fill="{accent}" fill-opacity="0.14" stroke="{accent}" stroke-opacity="0.45" stroke-width="2"/>
  <circle cx="300" cy="145" r="52" fill="{accent}" fill-opacity="0.18" stroke="{accent}" stroke-opacity="0.55" stroke-width="2"/>
  <line x1="80" y1="640" x2="520" y2="640" stroke="{accent}" stroke-opacity="0.4" stroke-width="1.5"/>
  <text x="300" y="455" text-anchor="middle" font-family="Rajdhani, Segoe UI, Arial, sans-serif" font-size="132" font-weight="700" fill="#ECE8E1" fill-opacity="0.14" letter-spacing="10">{initials}</text>
  <text x="300" y="695" text-anchor="middle" font-family="Rajdhani, Segoe UI, Arial, sans-serif" font-size="44" font-weight="700" fill="#ECE8E1" fill-opacity="0.72" letter-spacing="8">{safe_name}</text>
  <text x="300" y="730" text-anchor="middle" font-family="Rajdhani, Segoe UI, Arial, sans-serif" font-size="18" font-weight="600" fill="{accent}" letter-spacing="5">// {safe_role} PROTOCOL</text>
</svg>
"""
        (FALLBACK_DIR / f"agent_{slug}_portrait.svg").write_text(portrait_svg, encoding="utf-8")

    # Map fallback splash wallpapers
    for map_name in ALL_13_MAPS:
        slug = _slug(map_name)
        meta = MAP_FALLBACK_META.get(map_name, {"coords": "00°00'N,00°00'E", "accent": "#FF4655", "bg": "#0F1923"})
        accent = meta["accent"]
        bg = meta["bg"]
        safe_map = html.escape(map_name.upper())
        safe_coords = html.escape(meta["coords"])
        splash_svg = f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1600 900">
  <defs>
    <linearGradient id="m_{slug}" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0%" stop-color="{bg}"/>
      <stop offset="55%" stop-color="#0F1923"/>
      <stop offset="100%" stop-color="#090F16"/>
    </linearGradient>
    <radialGradient id="mg_{slug}" cx="75%" cy="28%" r="55%">
      <stop offset="0%" stop-color="{accent}" stop-opacity="0.32"/>
      <stop offset="100%" stop-color="{accent}" stop-opacity="0"/>
    </radialGradient>
  </defs>
  <rect width="1600" height="900" fill="url(#m_{slug})"/>
  <rect width="1600" height="900" fill="url(#mg_{slug})"/>
  <g stroke="#ECE8E1" stroke-opacity="0.06" stroke-width="1">
    <line x1="0" y1="180" x2="1600" y2="180"/><line x1="0" y1="360" x2="1600" y2="360"/>
    <line x1="0" y1="540" x2="1600" y2="540"/><line x1="0" y1="720" x2="1600" y2="720"/>
    <line x1="320" y1="0" x2="320" y2="900"/><line x1="640" y1="0" x2="640" y2="900"/>
    <line x1="960" y1="0" x2="960" y2="900"/><line x1="1280" y1="0" x2="1280" y2="900"/>
  </g>
  <polygon points="0,700 420,440 760,590 1160,310 1600,520 1600,900 0,900" fill="{accent}" fill-opacity="0.09" stroke="{accent}" stroke-opacity="0.3" stroke-width="2"/>
  <polygon points="180,900 580,560 980,690 1340,420 1600,610 1600,900" fill="#0B131C" fill-opacity="0.72"/>
  <text x="1500" y="790" text-anchor="end" font-family="Rajdhani, Segoe UI, Arial, sans-serif" font-size="140" font-weight="700" fill="#ECE8E1" fill-opacity="0.08" letter-spacing="18">{safe_map}</text>
  <text x="1500" y="838" text-anchor="end" font-family="Rajdhani, Segoe UI, Arial, sans-serif" font-size="22" font-weight="600" fill="{accent}" fill-opacity="0.55" letter-spacing="6">// SECTOR {safe_map} · {safe_coords}</text>
</svg>
"""
        (FALLBACK_DIR / f"map_{slug}_splash.svg").write_text(splash_svg, encoding="utf-8")


def _fetch_json(url: str, timeout: int = 12) -> list[dict]:
    req = urllib.request.Request(url, headers={"Accept": "application/json", "User-Agent": "VALOSENT-AI/2026"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        payload = json.loads(resp.read().decode("utf-8", errors="replace"))
        return payload.get("data", []) if isinstance(payload, dict) else []


def _load_agent_catalog() -> list[dict]:
    frame = pd.read_csv(AGENT_ROLES_PATH)
    frame.columns = [str(c).strip().casefold() for c in frame.columns]
    return [
        {"agent": str(row.agent).strip(), "role": str(row.role).strip()}
        for row in frame.dropna(subset=["agent", "role"]).itertuples(index=False)
    ]


def refresh_valorant_assets_cache(fetch_remote: bool = True) -> dict:
    """Fetch official valorant-api.com artwork, generate local fallbacks, and write JSON cache."""
    global _ASSET_CACHE
    catalog = _load_agent_catalog()
    _write_fallback_svgs(catalog)

    remote_agents: dict[str, dict] = {}
    remote_maps: dict[str, dict] = {}
    source_status = "fallback_only"

    if fetch_remote:
        try:
            for item in _fetch_json(VALORANT_AGENTS_API):
                name = str(item.get("displayName", "")).strip()
                if name:
                    remote_agents[_norm(name)] = item
            for item in _fetch_json(VALORANT_MAPS_API):
                name = str(item.get("displayName", "")).strip()
                if name and item.get("splash"):
                    remote_maps[_norm(name)] = item
            if remote_agents or remote_maps:
                source_status = "valorant-api.com + local fallbacks"
        except (urllib.error.URLError, TimeoutError, ValueError, OSError) as exc:
            LOGGER.warning("Could not reach valorant-api.com (%s); using local fallbacks.", exc)

    agents_out: dict[str, dict] = {}
    for entry in catalog:
        name = entry["agent"]
        role = entry["role"]
        slug = _slug(name)
        r_slug = _slug(role)
        remote = remote_agents.get(_norm(name), {})
        role_info = remote.get("role") or {}
        colors = remote.get("backgroundGradientColors") or []
        accent = f"#{colors[0][:6]}" if colors and len(colors[0]) >= 6 else ROLE_COLORS.get(role, "#FF4655")

        fb_icon = f"/static/assets/fallbacks/agent_{slug}_icon.svg"
        fb_portrait = f"/static/assets/fallbacks/agent_{slug}_portrait.svg"
        fb_role = f"/static/assets/fallbacks/role_{r_slug}.svg"

        agents_out[name] = {
            "agent": name,
            "role": role,
            "icon": remote.get("displayIcon") or fb_icon,
            "fallback_icon": fb_icon,
            "portrait": remote.get("fullPortrait") or remote.get("fullPortraitV2") or remote.get("bustPortrait") or fb_portrait,
            "fallback_portrait": fb_portrait,
            "background": remote.get("background") or None,
            "role_icon": role_info.get("displayIcon") or fb_role,
            "fallback_role_icon": fb_role,
            "accent": accent,
            "official_art": bool(remote.get("displayIcon")),
        }

    maps_out: dict[str, dict] = {}
    for map_name in ALL_13_MAPS:
        slug = _slug(map_name)
        remote = remote_maps.get(_norm(map_name), {})
        meta = MAP_FALLBACK_META.get(map_name, {"coords": "00°00'N,00°00'E", "accent": "#FF4655"})
        fb_splash = f"/static/assets/fallbacks/map_{slug}_splash.svg"
        maps_out[map_name] = {
            "map": map_name,
            "splash": remote.get("splash") or fb_splash,
            "fallback_splash": fb_splash,
            "banner": remote.get("listViewIcon") or remote.get("splash") or fb_splash,
            "minimap": remote.get("displayIcon") or None,
            "coordinates": remote.get("coordinates") or meta["coords"],
            "accent": meta["accent"],
            "official_art": bool(remote.get("splash")),
        }

    payload = {
        "source": source_status,
        "agents": agents_out,
        "maps": maps_out,
        "roles": {
            role: {
                "role": role,
                "icon": next(
                    (a["role_icon"] for a in agents_out.values() if a["role"] == role and a["official_art"]),
                    f"/static/assets/fallbacks/role_{_slug(role)}.svg",
                ),
                "fallback_icon": f"/static/assets/fallbacks/role_{_slug(role)}.svg",
                "color": ROLE_COLORS[role],
            }
            for role in ROLE_COLORS
        },
    }
    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    CACHE_PATH.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    _ASSET_CACHE = payload
    return payload


def get_all_assets() -> dict:
    global _ASSET_CACHE
    if _ASSET_CACHE is not None:
        return _ASSET_CACHE
    with _ASSET_LOCK:
        if _ASSET_CACHE is not None:
            return _ASSET_CACHE
        if CACHE_PATH.exists():
            try:
                _ASSET_CACHE = json.loads(CACHE_PATH.read_text(encoding="utf-8"))
                return _ASSET_CACHE
            except (OSError, json.JSONDecodeError):
                pass
        return refresh_valorant_assets_cache(fetch_remote=False)


def get_agent_asset(agent_name: str, role: str | None = None) -> dict:
    assets = get_all_assets().get("agents", {})
    if agent_name in assets:
        return assets[agent_name]
    key = _norm(agent_name)
    for item in assets.values():
        if _norm(item.get("agent", "")) == key:
            return item
    slug = _slug(agent_name) or "agent"
    role_key = role or "Duelist"
    fb_role = f"/static/assets/fallbacks/role_{_slug(role_key)}.svg"
    return {
        "agent": agent_name,
        "role": role_key,
        "icon": f"/static/assets/fallbacks/agent_{slug}_icon.svg",
        "fallback_icon": f"/static/assets/fallbacks/agent_{slug}_icon.svg",
        "portrait": f"/static/assets/fallbacks/agent_{slug}_portrait.svg",
        "fallback_portrait": f"/static/assets/fallbacks/agent_{slug}_portrait.svg",
        "background": None,
        "role_icon": fb_role,
        "fallback_role_icon": fb_role,
        "accent": ROLE_COLORS.get(role_key, "#FF4655"),
        "official_art": False,
    }


def get_map_asset(map_name: str) -> dict:
    assets = get_all_assets().get("maps", {})
    if map_name in assets:
        return assets[map_name]
    key = _norm(map_name)
    for item in assets.values():
        if _norm(item.get("map", "")) == key:
            return item
    slug = _slug(map_name) or "summit"
    meta = MAP_FALLBACK_META.get(map_name, {"coords": "// VALOSENT SECTOR", "accent": "#FF4655"})
    fb_splash = f"/static/assets/fallbacks/map_{slug}_splash.svg"
    return {
        "map": map_name,
        "splash": fb_splash,
        "fallback_splash": fb_splash,
        "banner": fb_splash,
        "minimap": None,
        "coordinates": meta["coords"],
        "accent": meta["accent"],
        "official_art": False,
    }


if __name__ == "__main__":
    result = refresh_valorant_assets_cache(fetch_remote=True)
    official_agents = sum(1 for a in result["agents"].values() if a["official_art"])
    official_maps = sum(1 for m in result["maps"].values() if m["official_art"])
    print(f"Assets cached ({result['source']}): {official_agents}/{len(result['agents'])} official agents, {official_maps}/{len(result['maps'])} official maps.")
