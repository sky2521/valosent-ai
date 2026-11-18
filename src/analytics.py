from __future__ import annotations

import itertools
import json
import re
from functools import lru_cache
from pathlib import Path

import pandas as pd

BASE_DIR = Path(__file__).resolve().parents[1]
CLEAN_MATCHES_PATH = BASE_DIR / "data" / "processed" / "matches" / "valorant_pro_matches_clean.parquet"
AGENT_ROLES_PATH = BASE_DIR / "data" / "agents" / "agent_roles.csv"
CONFIG_PATH = BASE_DIR / "config" / "analytics.json"


def normalize_name(value: str) -> str:
    return re.sub(r"[^a-z0-9]", "", str(value).casefold())


@lru_cache(maxsize=1)
def _get_config() -> dict:
    return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def _load_matches() -> pd.DataFrame:
    if not CLEAN_MATCHES_PATH.exists():
        raise FileNotFoundError("Run `python -m src.data_loader` before using match analytics.")

    matches = pd.read_parquet(CLEAN_MATCHES_PATH)
    roles = pd.read_csv(AGENT_ROLES_PATH)
    roles["agent_key"] = roles["agent"].map(normalize_name)
    role_by_key = roles.set_index("agent_key")["role"].to_dict()
    name_by_key = roles.set_index("agent_key")["agent"].to_dict()

    matches["agent_key"] = matches["agent"].map(normalize_name)
    matches["agent_name"] = matches["agent_key"].map(name_by_key).fillna(matches["agent"])
    matches["role"] = matches["agent_key"].map(role_by_key)
    return matches


def _to_records(frame: pd.DataFrame) -> list[dict]:
    return json.loads(frame.to_json(orient="records"))


@lru_cache(maxsize=1)
def _get_agent_map_stats() -> pd.DataFrame:
    matches = _load_matches()
    stats = (
        matches.groupby(["map", "agent_name", "role"], dropna=False)
        .agg(
            appearances=("map_group_id", "size"),
            resolved_maps=("player_won_map", "count"),
            wins=("player_won_map", "sum"),
            attack_acs_median=("acs-t", "median"),
            attack_acs_samples=("acs-t", "count"),
            defense_acs_median=("acs-ct", "median"),
            defense_acs_samples=("acs-ct", "count"),
        )
        .reset_index()
    )
    map_groups = matches.groupby("map")["map_group_id"].nunique().rename("map_groups")
    stats = stats.merge(map_groups, on="map", how="left", validate="many_to_one")
    stats["pick_rate"] = stats["appearances"] / (stats["map_groups"] * 10)
    stats["map_win_rate"] = stats["wins"] / stats["resolved_maps"].replace(0, pd.NA)

    z = _get_config()["wilson_z"]
    n = stats["resolved_maps"].where(stats["resolved_maps"].gt(0))
    proportion = stats["map_win_rate"]
    denominator = 1 + (z * z / n)
    center = proportion + (z * z / (2 * n))
    margin = z * (((proportion * (1 - proportion) / n) + (z * z / (4 * n * n))).clip(lower=0) ** 0.5)
    stats["win_rate_lower_bound"] = (center - margin) / denominator
    return stats


def _wilson_lower_bound(wins: pd.Series, total: pd.Series, z: float) -> pd.Series:
    n = total.where(total.gt(0))
    proportion = wins / n
    denominator = 1 + (z * z / n)
    center = proportion + (z * z / (2 * n))
    margin = z * (((proportion * (1 - proportion) / n) + (z * z / (4 * n * n))).clip(lower=0) ** 0.5)
    return (center - margin) / denominator


@lru_cache(maxsize=1)
def _get_composition_stats() -> pd.DataFrame:
    matches = _load_matches()
    team_maps = (
        matches.groupby(["map_group_id", "map", "player-team"], as_index=False)
        .agg(
            agents=("agent_name", lambda values: tuple(sorted(set(values)))),
            won=("player_won_map", "first"),
        )
    )
    team_maps = team_maps[team_maps["agents"].map(len).eq(5) & team_maps["won"].notna()].copy()
    team_maps["won"] = team_maps["won"].astype(int)
    team_maps["composition"] = team_maps["agents"].map(" | ".join)
    compositions = (
        team_maps.groupby(["map", "composition"], as_index=False)
        .agg(
            appearances=("map_group_id", "size"),
            wins=("won", "sum"),
        )
    )
    compositions["win_rate"] = compositions["wins"] / compositions["appearances"]
    compositions["win_rate_lower_bound"] = _wilson_lower_bound(
        compositions["wins"], compositions["appearances"], _get_config()["wilson_z"],
    )
    return compositions


@lru_cache(maxsize=1)
def _get_pair_stats() -> pd.DataFrame:
    matches = _load_matches()
    rows = []
    for (group_id, map_name, team_name), team_map in matches.groupby(
        ["map_group_id", "map", "player-team"], sort=False
    ):
        agents = sorted(set(team_map["agent_name"]))
        if len(agents) != 5:
            continue
        won_val = team_map["player_won_map"].iloc[0]
        if pd.isna(won_val):
            continue
        won = bool(won_val)
        for agent_a, agent_b in itertools.combinations(agents, 2):
            rows.append((group_id, map_name, team_name, agent_a, agent_b, won))

    pairs = pd.DataFrame(
        rows,
        columns=["map_group_id", "map", "player-team", "agent_a", "agent_b", "won"],
    )
    grouped = (
        pairs.groupby(["map", "agent_a", "agent_b"], as_index=False)
        .agg(appearances=("map_group_id", "size"), wins=("won", "sum"))
        .assign(win_rate=lambda frame: frame["wins"] / frame["appearances"])
    )
    grouped["win_rate_lower_bound"] = _wilson_lower_bound(
        grouped["wins"], grouped["appearances"], _get_config()["wilson_z"],
    )
    return grouped


def get_maps() -> list[str]:
    return sorted(_load_matches()["map"].dropna().unique().tolist())


def get_agents() -> list[dict]:
    matches = _load_matches()
    return _to_records(
        matches[["agent_name", "role"]]
        .drop_duplicates()
        .rename(columns={"agent_name": "agent"})
        .sort_values("agent")
    )


def get_roles() -> list[str]:
    return sorted(_load_matches()["role"].dropna().unique().tolist())


def get_dataset_summary() -> dict:
    matches = _load_matches()
    return {
        "map_groups": int(matches["map_group_id"].nunique()),
        "maps": len(get_maps()),
        "agents": len(get_agents()),
        "roles": get_roles(),
        "player_labels": int(matches["player-name"].nunique()),
        "date_start": matches["match-datetime"].min().date().isoformat(),
        "date_end": matches["match-datetime"].max().date().isoformat(),
        "events": None,
        "regions": None,
    }


def get_agent_comparison(agent_names: list[str], map_name: str | None = None) -> list[dict]:
    requested = {normalize_name(name) for name in agent_names}
    stats = _get_agent_map_stats()
    stats = stats[stats["agent_name"].map(normalize_name).isin(requested)]
    if map_name and map_name.casefold() != "all":
        stats = stats[stats["map"].str.casefold().eq(map_name.casefold())]
    return _to_records(stats.sort_values(["agent_name", "map"]))


def get_agent_comparison_summary(agent_names: list[str], map_name: str | None = None) -> dict:
    """Build rich side-by-side agent profiles, metric winners, and pair synergies."""
    canonical_map = None
    if map_name and map_name.casefold() != "all":
        canonical_map = next((value for value in get_maps() if value.casefold() == map_name.casefold()), None)

    profiles = []
    seen_keys = set()
    for raw_name in agent_names:
        key = normalize_name(raw_name)
        if key in seen_keys:
            continue
        seen_keys.add(key)
        agent_data = get_agent_stats(raw_name)
        if agent_data is None:
            continue

        all_maps = agent_data["maps"]
        min_picks = _get_config()["minimum_map_picks"]
        qualified = [m for m in all_maps if m["resolved_maps"] >= min_picks] or all_maps
        best_map_entry = max(qualified, key=lambda m: (m["win_rate_lower_bound"] or 0.0, m["appearances"])) if qualified else None
        worst_map_entry = min(qualified, key=lambda m: (m["win_rate_lower_bound"] or 0.0, -m["appearances"])) if qualified else None

        if canonical_map:
            scoped = next((m for m in all_maps if m["map"] == canonical_map), None)
            if scoped:
                appearances = int(scoped["appearances"])
                pick_rate = scoped["pick_rate"]
                map_win_rate = scoped["map_win_rate"]
                attack_acs = scoped["attack_acs_median"]
                defense_acs = scoped["defense_acs_median"]
            else:
                appearances = 0
                pick_rate = 0.0
                map_win_rate = None
                attack_acs = None
                defense_acs = None
        else:
            overall = agent_data["overall"]
            appearances = int(overall["appearances"])
            pick_rate = overall["pick_rate"]
            map_win_rate = overall["map_win_rate"]
            attack_acs = overall["attack_acs_median"]
            defense_acs = overall["defense_acs_median"]

        profiles.append({
            "agent": agent_data["agent"],
            "role": agent_data["role"],
            "appearances": appearances,
            "pick_rate": pick_rate,
            "map_win_rate": map_win_rate,
            "attack_acs_median": attack_acs,
            "defense_acs_median": defense_acs,
            "best_map": best_map_entry["map"] if best_map_entry else None,
            "best_map_win_rate": best_map_entry["map_win_rate"] if best_map_entry else None,
            "worst_map": worst_map_entry["map"] if worst_map_entry else None,
            "worst_map_win_rate": worst_map_entry["map_win_rate"] if worst_map_entry else None,
        })

    # Compute pair synergies between selected agents (either on canonical_map or aggregated across all maps)
    pairs_df = _get_pair_stats()
    if canonical_map:
        pairs_df = pairs_df[pairs_df["map"].eq(canonical_map)]
    z = _get_config()["wilson_z"]
    pair_synergies = []
    for prof_a, prof_b in itertools.combinations(profiles, 2):
        a_name, b_name = sorted((prof_a["agent"], prof_b["agent"]))
        hits = pairs_df[pairs_df["agent_a"].eq(a_name) & pairs_df["agent_b"].eq(b_name)]
        apps = int(hits["appearances"].sum()) if not hits.empty else 0
        wins = int(hits["wins"].sum()) if not hits.empty else 0
        wr = (wins / apps) if apps > 0 else None
        lb = float(_wilson_lower_bound(pd.Series([wins]), pd.Series([apps]), z).iloc[0]) if apps > 0 else None
        role_note = (
            f"Complementary ({prof_a['role']} + {prof_b['role']})"
            if prof_a["role"] != prof_b["role"]
            else f"Double {prof_a['role']} stack"
        )
        pair_synergies.append({
            "agent_a": prof_a["agent"],
            "agent_b": prof_b["agent"],
            "role_synergy": role_note,
            "appearances": apps,
            "wins": wins,
            "win_rate": round(wr, 4) if wr is not None else None,
            "win_rate_lower_bound": round(lb, 4) if lb is not None else None,
        })

    return {
        "profiles": profiles,
        "pair_synergies": pair_synergies,
    }


def get_map_agent_stats(map_name: str | None = None, role: str | None = None) -> list[dict]:
    stats = _get_agent_map_stats()
    if map_name and map_name.casefold() != "all":
        matches = stats[stats["map"].str.casefold().eq(map_name.casefold())]
        if matches.empty:
            return []
        stats = matches
    if role and role.casefold() != "all":
        stats = stats[stats["role"].str.casefold().eq(role.casefold())]
    return _to_records(stats.sort_values(["map", "appearances"], ascending=[True, False]))


def get_map_stats(map_name: str) -> dict | None:
    canonical_map = next((value for value in get_maps() if value.casefold() == map_name.casefold()), None)
    if canonical_map is None:
        return None
    matches = _load_matches()
    map_matches = matches[matches["map"].eq(canonical_map)]
    agent_stats = _get_agent_map_stats()
    agent_stats = agent_stats[agent_stats["map"].eq(canonical_map)]
    return {
        "map": canonical_map,
        "map_groups": int(map_matches["map_group_id"].nunique()),
        "player_agent_picks": int(len(map_matches)),
        "agents": _to_records(agent_stats.sort_values("appearances", ascending=False)),
        "data_period": {
            "start": map_matches["match-datetime"].min().date().isoformat(),
            "end": map_matches["match-datetime"].max().date().isoformat(),
        },
    }


def get_agent_stats(agent_name: str) -> dict | None:
    key = normalize_name(agent_name)
    stats = _get_agent_map_stats()
    agent_stats = stats[stats["agent_name"].map(normalize_name).eq(key)]
    if agent_stats.empty:
        return None
    canonical_name = agent_stats.iloc[0]["agent_name"]
    matches = _load_matches()
    agent_rows = matches[matches["agent_name"].map(normalize_name).eq(key)]
    resolved = agent_rows["player_won_map"].dropna()
    total_map_groups = int(matches["map_group_id"].nunique())
    minimum_picks = _get_config()["minimum_map_picks"]
    qualified_maps = agent_stats[agent_stats["resolved_maps"].ge(minimum_picks)]

    return {
        "agent": canonical_name,
        "role": agent_stats.iloc[0]["role"],
        "overall": {
            "appearances": int(len(agent_rows)),
            "pick_rate": len(agent_rows) / (total_map_groups * 10) if total_map_groups else None,
            "resolved_maps": int(len(resolved)),
            "wins": int(resolved.sum()) if len(resolved) else 0,
            "map_win_rate": float(resolved.mean()) if len(resolved) else None,
            "attack_acs_median": float(agent_rows["acs-t"].median()) if agent_rows["acs-t"].notna().any() else None,
            "attack_acs_samples": int(agent_rows["acs-t"].count()),
            "defense_acs_median": float(agent_rows["acs-ct"].median()) if agent_rows["acs-ct"].notna().any() else None,
            "defense_acs_samples": int(agent_rows["acs-ct"].count()),
        },
        "best_maps": _to_records(qualified_maps.sort_values("win_rate_lower_bound", ascending=False).head(3)),
        "worst_maps": _to_records(qualified_maps.sort_values("win_rate_lower_bound").head(3)),
        "minimum_map_picks_for_ranked_maps": minimum_picks,
        "maps": _to_records(agent_stats.sort_values("win_rate_lower_bound", ascending=False)),
    }


def get_best_agents_for_map(
    map_name: str,
    side: str = "both",
    role: str | None = None,
    limit: int = 3,
) -> dict:
    canonical_map = next((value for value in get_maps() if value.casefold() == map_name.casefold()), None)
    if canonical_map is None:
        return {"status": "unknown_map", "map": map_name, "recommendations": []}

    side = side.casefold()
    if side not in {"both", "attack", "defense"}:
        return {"status": "invalid_side", "map": canonical_map, "recommendations": []}

    config = _get_config()
    candidates = _get_agent_map_stats()
    candidates = candidates[candidates["map"].eq(canonical_map)]
    if role and role.casefold() != "all":
        candidates = candidates[candidates["role"].str.casefold().eq(role.casefold())]

    if side == "both":
        candidates = candidates[candidates["appearances"].ge(config["minimum_map_picks"])].copy()
        ranking_column = "win_rate_lower_bound"
        score_label = "Wilson 95% lower bound of historical map win rate"
        if candidates.empty:
            return {"status": "insufficient_data", "map": canonical_map, "side": side, "recommendations": []}
        candidates["score"] = candidates[ranking_column] * 100
        candidates = candidates.sort_values([ranking_column, "appearances"], ascending=[False, False])
    else:
        metric_column = "attack_acs_median" if side == "attack" else "defense_acs_median"
        sample_column = "attack_acs_samples" if side == "attack" else "defense_acs_samples"
        candidates = candidates[
            candidates["appearances"].ge(config["minimum_map_picks"])
            & candidates[sample_column].ge(config["minimum_side_samples"])
            & candidates[metric_column].notna()
        ].copy()
        if candidates.empty:
            return {"status": "insufficient_data", "map": canonical_map, "side": side, "recommendations": []}
        score_label = f"Percentile of median {side.title()}-side ACS among eligible agents"
        candidates["score"] = candidates[metric_column].rank(pct=True, method="average") * 100
        candidates = candidates.sort_values([metric_column, "appearances"], ascending=[False, False])

    recommendations = []
    for row in candidates.head(limit).to_dict(orient="records"):
        why = [
            f"{row['map_win_rate']:.1%} historical map win rate across {int(row['resolved_maps'])} resolved picks",
            f"{row['pick_rate']:.1%} of agent picks on this map",
        ]
        if side == "attack":
            why.append(f"Median T-side ACS {row['attack_acs_median']:.1f} from {int(row['attack_acs_samples'])} samples")
        elif side == "defense":
            why.append(f"Median CT-side ACS {row['defense_acs_median']:.1f} from {int(row['defense_acs_samples'])} samples")
        recommendations.append({
            "rank": len(recommendations) + 1,
            "agent": row["agent_name"],
            "role": row["role"],
            "score": round(float(row["score"]), 2),
            "score_label": score_label,
            "pick_count": int(row["appearances"]),
            "pick_rate": row["pick_rate"],
            "map_win_rate": row["map_win_rate"],
            "attack_acs_median": row["attack_acs_median"],
            "attack_acs_samples": int(row["attack_acs_samples"]),
            "defense_acs_median": row["defense_acs_median"],
            "defense_acs_samples": int(row["defense_acs_samples"]),
            "why": why,
        })

    return {
        "status": "ok",
        "map": canonical_map,
        "side": side,
        "role": role or "All",
        "minimum_map_picks": config["minimum_map_picks"],
        "recommendations": recommendations,
    }


def get_best_team_compositions(map_name: str, limit: int = 5) -> dict:
    canonical_map = next((value for value in get_maps() if value.casefold() == map_name.casefold()), None)
    if canonical_map is None:
        return {"status": "unknown_map", "map": map_name, "compositions": []}
    minimum = _get_config()["minimum_composition_appearances"]
    candidates = _get_composition_stats()
    candidates = candidates[
        candidates["map"].eq(canonical_map)
        & candidates["appearances"].ge(minimum)
    ].copy()
    if candidates.empty:
        return {"status": "insufficient_data", "map": canonical_map, "compositions": []}
    candidates = candidates.sort_values(["win_rate_lower_bound", "appearances"], ascending=[False, False])
    return {
        "status": "ok",
        "map": canonical_map,
        "minimum_appearances": minimum,
        "ranking_method": "Wilson 95% lower bound of historical composition win rate",
        "compositions": _to_records(candidates.head(limit)),
        "label": "Historical compositions in the available dataset (Wilson 95% lower bound)",
    }


def get_agent_synergy(agent_name: str, map_name: str | None = None, limit: int = 10) -> dict:
    key = normalize_name(agent_name)
    agent_names = {normalize_name(name): name for name in _load_matches()["agent_name"].unique()}
    canonical_agent = agent_names.get(key)
    if canonical_agent is None:
        return {"status": "unknown_agent", "agent": agent_name, "pairings": []}

    pairs = _get_pair_stats()
    pairings = pairs[(pairs["agent_a"].eq(canonical_agent)) | (pairs["agent_b"].eq(canonical_agent))].copy()
    if map_name and map_name.casefold() != "all":
        pairings = pairings[pairings["map"].str.casefold().eq(map_name.casefold())]
    minimum = _get_config()["minimum_composition_appearances"]
    pairings = pairings[pairings["appearances"].ge(minimum)].copy()
    other = pairings["agent_b"].where(pairings["agent_a"].eq(canonical_agent), pairings["agent_a"])
    pairings["partner"] = other
    pairings = pairings.sort_values(["win_rate_lower_bound", "appearances"], ascending=[False, False])
    return {
        "status": "ok" if not pairings.empty else "insufficient_data",
        "agent": canonical_agent,
        "map": map_name or "All",
        "minimum_appearances": minimum,
        "ranking_method": "Wilson 95% lower bound of historical pairing win rate",
        "pairings": _to_records(
            pairings[["map", "partner", "appearances", "wins", "win_rate", "win_rate_lower_bound"]].head(limit)
        ),
    }


def get_draft_context(map_name: str, team1_agents: list[str], team2_agents: list[str]) -> dict:
    """Summarize role balance, historical composition support, and pair synergy for a 5v5 draft."""
    canonical_map = next((value for value in get_maps() if value.casefold() == map_name.casefold()), None)
    if canonical_map is None:
        return {"status": "unknown_map", "map": map_name}

    agent_catalog = {normalize_name(item["agent"]): item for item in get_agents()}
    compositions = _get_composition_stats()
    map_comps = compositions[compositions["map"].eq(canonical_map)]
    pairs = _get_pair_stats()
    map_pairs = pairs[pairs["map"].eq(canonical_map)]
    all_roles = ("Controller", "Duelist", "Initiator", "Sentinel")

    def summarize_team(raw_agents: list[str]) -> dict:
        canonical = []
        role_counts = {role: 0 for role in all_roles}
        for name in raw_agents:
            entry = agent_catalog.get(normalize_name(name))
            if entry is None:
                return {"error": f"Unknown or unsupported agent: {name}"}
            canonical.append(entry["agent"])
            if entry["role"] in role_counts:
                role_counts[entry["role"]] += 1

        if len(set(canonical)) != 5:
            return {"error": "Each team must select 5 distinct agents."}

        sorted_agents = sorted(canonical)
        comp_key = " | ".join(sorted_agents)
        comp_match = map_comps[map_comps["composition"].eq(comp_key)]
        if not comp_match.empty:
            row = comp_match.iloc[0]
            comp_stats = {
                "appearances": int(row["appearances"]),
                "wins": int(row["wins"]),
                "win_rate": round(float(row["win_rate"]), 4),
                "win_rate_lower_bound": round(float(row["win_rate_lower_bound"]), 4),
            }
        else:
            comp_stats = None

        pair_records = []
        for agent_a, agent_b in itertools.combinations(sorted_agents, 2):
            hit = map_pairs[map_pairs["agent_a"].eq(agent_a) & map_pairs["agent_b"].eq(agent_b)]
            if not hit.empty:
                row = hit.iloc[0]
                pair_records.append({
                    "pair": f"{agent_a} + {agent_b}",
                    "appearances": int(row["appearances"]),
                    "win_rate": round(float(row["win_rate"]), 4),
                })

        weighted_synergy = None
        if pair_records:
            total_pair_apps = sum(item["appearances"] for item in pair_records)
            if total_pair_apps > 0:
                weighted_synergy = round(
                    sum(item["win_rate"] * item["appearances"] for item in pair_records) / total_pair_apps,
                    4,
                )

        missing_roles = [role for role, count in role_counts.items() if count == 0]
        warnings = []
        if role_counts["Controller"] == 0:
            warnings.append("No Controller (missing smoke/vision denial).")
        if role_counts["Initiator"] == 0:
            warnings.append("No Initiator (limited recon/flash setup).")
        if role_counts["Duelist"] == 0:
            warnings.append("No Duelist (slower site entry).")
        if role_counts["Sentinel"] == 0:
            warnings.append("No Sentinel (weaker flank watch / post-plant hold).")

        return {
            "agents": sorted_agents,
            "role_counts": role_counts,
            "missing_roles": missing_roles,
            "warnings": warnings,
            "historical_composition": comp_stats,
            "average_pair_win_rate": weighted_synergy,
            "observed_pairs": len(pair_records),
            "top_pairs": sorted(pair_records, key=lambda item: (-item["win_rate"], -item["appearances"]))[:3],
        }

    team1_summary = summarize_team(team1_agents)
    if "error" in team1_summary:
        return {"status": "invalid_lineup", "error": f"Team 1: {team1_summary['error']}"}
    team2_summary = summarize_team(team2_agents)
    if "error" in team2_summary:
        return {"status": "invalid_lineup", "error": f"Team 2: {team2_summary['error']}"}

    return {
        "status": "ok",
        "map": canonical_map,
        "team1": team1_summary,
        "team2": team2_summary,
    }