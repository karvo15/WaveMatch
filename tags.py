"""
Shared tag matching and maintenance (Phase N).

Spec: 3-Full-Product-Logic.md Section 10.1 (fixed list), 10.2 (layered matching),
10.3 (nightly deduplication).

This module exists so the *one* implementation of the Section 10.2 layered process is
called by both sides that parse free-text tags -- user interests (`registration.py`) and
poster tags (`poster_flow.py`) -- rather than the two keeping their own copies in step.
It also owns the Section 10.3 merge job, because "which two tags are the same tag" is the
same question as "which tag does this term mean", and answering it two different ways is
exactly how matching silently breaks over time.

The layered process, in order:
    1. normalize      -- lowercase, trim, strip punctuation
    2. exact match    against the 12 fixed categories
    3. substring/keyword match ("hackathon" -> "Competitions / Hackathons")
    4. fuzzy match    (rapidfuzz, typo tolerance: "scholarshp" -> "Scholarships")
    5. alias dictionary ("job" -> "Job Opportunities", "comp" -> "Competitions / Hackathons")
    6. fallback       -- store as a new custom tag, lowercased and trimmed
"""

import logging
import re
from typing import Any, Dict, Iterable, List, Optional

import anyio
from rapidfuzz import fuzz, process

from conversation import _db_semaphore
from database import supabase

logger = logging.getLogger(__name__)

# The fixed starter list (Section 10.1 / 1-Product-Plan.md). Shown to posters and users as
# plain text; 5-Data-Schema.sql seeds these same 12 with is_custom = false.
FIXED_CATEGORIES: List[str] = [
    "Scholarships",
    "Internships",
    "Volunteering",
    "Tech Events / Conferences",
    "Competitions / Hackathons",
    "Workshops / Trainings",
    "Bootcamps",
    "Job Opportunities",
    "Research Opportunities",
    "Fellowships",
    "Grants / Funding",
    "Networking Events",
]

# Alternate words that mean the same thing but are not typos, so layer 4 can't reach them
# (Section 10.2, layer 5: "a short, manually maintained list").
ALIASES: Dict[str, str] = {
    # Spec's own examples.
    "job": "Job Opportunities",
    "grant": "Grants / Funding",
    "intern": "Internships",
    "comp": "Competitions / Hackathons",
    # The same idea for the other ten categories.
    "jobs": "Job Opportunities",
    "grants": "Grants / Funding",
    "funding": "Grants / Funding",
    "interns": "Internships",
    "internship": "Internships",
    "comps": "Competitions / Hackathons",
    "hack": "Competitions / Hackathons",
    "hackathon": "Competitions / Hackathons",
    "hackathons": "Competitions / Hackathons",
    "schol": "Scholarships",
    "scholarship": "Scholarships",
    "volunteer": "Volunteering",
    "fellowship": "Fellowships",
    "fellow": "Fellowships",
    "research": "Research Opportunities",
    "bootcamp": "Bootcamps",
    "bootcamps": "Bootcamps",
    "workshop": "Workshops / Trainings",
    "workshops": "Workshops / Trainings",
    "training": "Workshops / Trainings",
    "trainings": "Workshops / Trainings",
    "conference": "Tech Events / Conferences",
    "conferences": "Tech Events / Conferences",
    "event": "Tech Events / Conferences",
    "events": "Tech Events / Conferences",
    "networking": "Networking Events",
    "network": "Networking Events",
}

# Layer 4 threshold, on rapidfuzz's `fuzz.ratio` (normalized edit distance).
FUZZY_CUTOFF = 80

# Six of the twelve categories are multi-word ("Competitions / Hackathons"), and layer 4
# scores against the whole name -- so a typo'd "hacksthond" scores 44 against the full
# name and matches nothing, even though it is one character from the keyword. Scoring each
# keyword as well fixes that (and is how the nightly job can clean up the tags that layer 4
# fails to catch). Short fragments are skipped: a 1-3 character keyword ("job") is within
# an edit or two of unrelated words, and that is layer 5's job anyway.
MIN_KEYWORD_LENGTH = 4

# Layer 3 needs enough characters to mean anything -- a 1-2 character term is a substring
# of almost every category name, so "a" must not resolve to "Scholarships".
MIN_SUBSTRING_LENGTH = 3

# Layer 6 stores custom tags lowercased and trimmed, exactly as Section 10.2 says.
CUSTOM_NAME_MAX_LENGTH = 60

_PUNCTUATION = ".,!?;:\"'()[]{}"
_TERM_SPLITTER = re.compile(r"[,;\n]")


def _normalize(text: str) -> str:
    """Layer 1: lowercase, trim whitespace, strip punctuation, collapse inner runs."""
    cleaned = (text or "").strip().lower()
    cleaned = cleaned.strip(_PUNCTUATION).strip()
    return " ".join(cleaned.split())


NORMALIZED_FIXED_CATEGORIES: List[str] = [_normalize(category) for category in FIXED_CATEGORIES]
_FIXED_BY_NORMALIZED: Dict[str, str] = dict(zip(NORMALIZED_FIXED_CATEGORIES, FIXED_CATEGORIES))

_WORD_SPLITTER = re.compile(r"[^a-z0-9]+")


def _keywords(category: str) -> List[str]:
    """The meaningful words inside a category name (\"grants\", \"funding\", \"hackathons\")."""
    return [
        word
        for word in _WORD_SPLITTER.split(_normalize(category))
        if len(word) >= MIN_KEYWORD_LENGTH
    ]


_KEYWORDS: Dict[str, List[str]] = {category: _keywords(category) for category in FIXED_CATEGORIES}


def match_term(term: str) -> Optional[str]:
    """
    Run layers 1-5 for one typed term.

    Returns the canonical fixed category name, or None when nothing matched confidently
    (in which case `parse_interests` falls back to layer 6).
    """
    normalized = _normalize(term)
    if not normalized:
        return None

    # Layer 2 -- exact.
    if normalized in _FIXED_BY_NORMALIZED:
        return _FIXED_BY_NORMALIZED[normalized]

    # Layer 3 -- substring / keyword. Both directions, so "hackathon" finds
    # "Competitions / Hackathons" and "tech events" finds the same category.
    if len(normalized) >= MIN_SUBSTRING_LENGTH:
        for category, normalized_category in zip(FIXED_CATEGORIES, NORMALIZED_FIXED_CATEGORIES):
            if normalized in normalized_category or normalized_category in normalized:
                return category

    # Layer 4 -- typo tolerance, against the whole category name and against each of its
    # keywords. Best score wins (ties keep the fixed list order, matching layer 3).
    best_category: Optional[str] = None
    best_score = 0.0
    for category, normalized_category in zip(FIXED_CATEGORIES, NORMALIZED_FIXED_CATEGORIES):
        score = fuzz.ratio(normalized, normalized_category)
        for keyword in _KEYWORDS[category]:
            score = max(score, fuzz.ratio(normalized, keyword))
        if score > best_score:
            best_category, best_score = category, score

    if best_category and best_score >= FUZZY_CUTOFF:
        return best_category

    # Layer 5 -- alias dictionary.
    return ALIASES.get(normalized)


def parse_interests(raw_text: str) -> List[Dict[str, Any]]:
    """
    Parse a comma-separated free-text reply into tags (Section 10.2, all six layers).

    Returns [{"name": <canonical or custom name>, "is_custom": bool}, ...], de-duplicated
    by name: several typed terms can resolve to one tag ("tech events, event"), and linking
    the same (user/opportunity, tag) pair twice would violate the junction primary key.
    """
    result: List[Dict[str, Any]] = []
    seen = set()

    for chunk in _TERM_SPLITTER.split(raw_text or ""):
        normalized = _normalize(chunk)
        if not normalized:
            continue

        canonical = match_term(normalized)
        if canonical:
            name, is_custom = canonical, False
        else:
            # Layer 6 -- fallback: the typed term becomes a new custom tag.
            name, is_custom = normalized[:CUSTOM_NAME_MAX_LENGTH], True

        key = name.lower()
        if key in seen:
            continue
        seen.add(key)
        result.append({"name": name, "is_custom": is_custom})

    return result
# ============================================================
# SHARED WRITE PATH (used by both interest parsing and poster tags)
# ============================================================

# The two junction tables that point at `tags`.
JUNCTIONS = (("user_tags", "user_id"), ("opportunity_tags", "opportunity_id"))


async def get_or_create_tag(name: str, is_custom: bool) -> Optional[str]:
    """
    Find a tag by name (case-insensitive) or create it.

    One implementation for both sides. Returns None for a non-custom name that isn't in
    the table -- that shouldn't happen (layer 6 always marks custom), but a silent None is
    better than writing a fixed tag that doesn't exist in the fixed list.
    """
    def _run():
        existing = supabase.from_("tags").select("id").ilike("name", name).limit(1).execute()
        if existing.data:
            return existing.data[0]["id"]
        if not is_custom:
            return None
        try:
            created = supabase.from_("tags").insert({"name": name, "is_custom": True}).execute()
        except Exception:
            # A concurrent create won the race (`tags.name` is UNIQUE) -- re-read instead
            # of surfacing a 23505 to the user mid-flow.
            again = supabase.from_("tags").select("id").ilike("name", name).limit(1).execute()
            if again.data:
                return again.data[0]["id"]
            raise
        return created.data[0]["id"] if created.data else None

    async with _db_semaphore:
        return await anyio.to_thread.run_sync(_run)


async def link_tags(
    junction_table: str, owner_column: str, owner_id: str, parsed: Iterable[Dict[str, Any]]
) -> List[str]:
    """
    Resolve parsed terms to tag ids and link them to one owner row.

    `upsert(ignore_duplicates)` rather than `insert`: two typed terms can resolve to the
    same tag id, and re-inserting a (owner, tag) pair would violate the composite primary
    key. Returns the tag ids that are now linked.
    """
    tag_ids: List[str] = []
    for item in parsed:
        tag_id = await get_or_create_tag(item["name"], item.get("is_custom", False))
        if tag_id and tag_id not in tag_ids:
            tag_ids.append(tag_id)

    if not tag_ids:
        return []

    def _link():
        return supabase.from_(junction_table).upsert(
            [{owner_column: owner_id, "tag_id": tag_id} for tag_id in tag_ids],
            ignore_duplicates=True,
        ).execute()

    async with _db_semaphore:
        await anyio.to_thread.run_sync(_link)
    return tag_ids


# ============================================================
# SECTION 10.3 -- NIGHTLY DEDUPLICATION
# ============================================================

# Two custom tags are treated as the same tag when their normalized stems are equal or
# near-equal. Deliberately conservative: a wrong merge silently rewrites what users
# receive, while a missed merge is just one more row for tomorrow night's run.
MERGE_CUTOFF = 87

# Trailing words that describe *what kind of thing* a tag is rather than what it is about.
# "Volunteer work" and "volunteer" are the same tag; "Volunteering" and "Networking
# Events" are not.
_FILLER_SUFFIXES = frozenset({
    "opportunity", "opportunities", "event", "events", "program", "programme", "programs",
    "work", "works", "related", "stuff", "thing", "things", "category", "categories",
})


def _stem(name: str) -> str:
    """Normalize, drop filler tails, and crudely singularize -- for comparing custom tags."""
    tokens = _normalize(name).split()
    while tokens and tokens[-1] in _FILLER_SUFFIXES:
        tokens.pop()
    stem = " ".join(tokens)
    for suffix, replacement in (("ies", "y"), ("es", ""), ("s", "")):
        if len(stem) > len(suffix) + 3 and stem.endswith(suffix):
            return stem[: -len(suffix)] + replacement
    return stem


def _same_tag(left: str, right: str) -> bool:
    left_normalized, right_normalized = _normalize(left), _normalize(right)
    if not left_normalized or not right_normalized:
        return False
    if left_normalized == right_normalized:
        return True
    left_stem, right_stem = _stem(left), _stem(right)
    if left_stem and left_stem == right_stem:
        return True
    return fuzz.ratio(left_stem or left_normalized, right_stem or right_normalized) >= MERGE_CUTOFF


def _fixed_target(name: str) -> Optional[str]:
    """
    The fixed category this name should belong to, if any.

    Tries the name as typed and its stem, so "Volunteer work" (which layer 5 can't reach)
    still lands on "Volunteering" -- the exact example Section 10.3 gives.
    """
    return match_term(name) or match_term(_stem(name))


def plan_tag_merges(
    tags: List[Dict[str, Any]], counts: Optional[Dict[str, int]] = None
) -> List[Dict[str, Any]]:
    """
    Decide which tags to merge, without touching the database (pure, so it is testable).

    Two rules, in order:
      1. A custom tag whose name resolves to a fixed category (via any layer of 10.2, or
         via its stem) belongs to that fixed category.
      2. Remaining custom tags whose stems match each other are grouped, and the
         most-referenced one wins (ties: oldest, then name) so the surviving name is the
         one users are most likely to already be subscribed to.

    Only `is_custom` tags are ever merged away and deleted -- a fixed category is never
    re-pointed or removed, so the 12 seeded tags stay canonical.

    Returns [{"canonical_id", "canonical_name", "duplicate_ids", "duplicate_names"}, ...].
    """
    counts = counts or {}
    fixed_by_name = {tag["name"]: tag for tag in tags if not tag.get("is_custom")}
    fixed_by_id = {tag["id"]: tag for tag in tags if not tag.get("is_custom")}
    custom_tags = [tag for tag in tags if tag.get("is_custom")]

    # Rule 1.
    by_canonical_id: Dict[str, List[Dict[str, Any]]] = {}
    leftovers: List[Dict[str, Any]] = []
    for tag in custom_tags:
        target = _fixed_target(tag["name"])
        if target and target in fixed_by_name:
            by_canonical_id.setdefault(fixed_by_name[target]["id"], []).append(tag)
        else:
            leftovers.append(tag)

    # Rule 2.
    groups: List[List[Dict[str, Any]]] = []
    for tag in sorted(leftovers, key=lambda row: (str(row.get("created_at") or ""), row["name"].lower())):
        for group in groups:
            if any(_same_tag(tag["name"], other["name"]) for other in group):
                group.append(tag)
                break
        else:
            groups.append([tag])

    plan: List[Dict[str, Any]] = []

    for canonical_id, duplicates in by_canonical_id.items():
        plan.append(
            {
                "canonical_id": canonical_id,
                "canonical_name": fixed_by_id[canonical_id]["name"],
                "duplicate_ids": [tag["id"] for tag in duplicates],
                "duplicate_names": [tag["name"] for tag in duplicates],
            }
        )

    for group in groups:
        if len(group) < 2:
            continue
        ordered = sorted(
            group,
            key=lambda tag: (-counts.get(tag["id"], 0), str(tag.get("created_at") or ""), tag["name"].lower()),
        )
        canonical, duplicates = ordered[0], ordered[1:]
        plan.append(
            {
                "canonical_id": canonical["id"],
                "canonical_name": canonical["name"],
                "duplicate_ids": [tag["id"] for tag in duplicates],
                "duplicate_names": [tag["name"] for tag in duplicates],
            }
        )

    return plan


async def _fetch_all_tags() -> List[Dict[str, Any]]:
    def _get():
        rows: List[Dict[str, Any]] = []
        start = 0
        while True:
            res = (
                supabase.from_("tags")
                .select("id, name, is_custom, created_at")
                .range(start, start + 999)
                .execute()
            )
            batch = res.data or []
            rows.extend(batch)
            if len(batch) < 1000:
                return rows
            start += 1000

    async with _db_semaphore:
        return await anyio.to_thread.run_sync(_get)


async def _fetch_reference_counts() -> Dict[str, int]:
    """How many users/opportunities point at each tag -- used to pick the surviving name."""
    def _get():
        counts: Dict[str, int] = {}
        for table, _ in JUNCTIONS:
            res = supabase.from_(table).select("tag_id").execute()
            for row in res.data or []:
                counts[row["tag_id"]] = counts.get(row["tag_id"], 0) + 1
        return counts

    async with _db_semaphore:
        return await anyio.to_thread.run_sync(_get)


async def _repoint(table: str, owner_column: str, duplicate_id: str, canonical_id: str) -> int:
    """
    Move every link from a duplicate tag onto the canonical tag.

    `ignore_duplicates` matters: an owner that already had both tags would otherwise
    collide on the junction primary key and fail the whole merge.
    """
    def _run():
        res = supabase.from_(table).select(owner_column).eq("tag_id", duplicate_id).execute()
        owners = [row[owner_column] for row in (res.data or [])]
        if owners:
            supabase.from_(table).upsert(
                [{owner_column: owner, "tag_id": canonical_id} for owner in owners],
                ignore_duplicates=True,
            ).execute()
        return len(owners)

    async with _db_semaphore:
        return await anyio.to_thread.run_sync(_run)


async def _delete_tag(tag_id: str) -> None:
    def _delete():
        return supabase.from_("tags").delete().eq("id", tag_id).execute()

    async with _db_semaphore:
        await anyio.to_thread.run_sync(_delete)


async def merge_near_duplicate_tags(dry_run: bool = False) -> Dict[str, Any]:
    """
    Section 10.3's nightly safety net: merge near-duplicate custom tags into one canonical
    tag, re-pointing the users and opportunities that referenced the duplicate.

    A duplicate tag is only deleted once *both* junction tables have been re-pointed --
    deleting it cascades its own links away, so deleting after a failed re-point would
    silently drop interests. `dry_run` computes the plan and changes nothing.
    """
    tags = await _fetch_all_tags()
    counts = await _fetch_reference_counts()
    plan = plan_tag_merges(tags, counts)

    summary: Dict[str, Any] = {
        "groups": len(plan),
        "duplicates": sum(len(entry["duplicate_ids"]) for entry in plan),
        "repointed_user_tags": 0,
        "repointed_opportunity_tags": 0,
        "deleted_tags": 0,
    }

    if dry_run:
        logger.info(f"TAG_DEDUP_DRY_RUN: {summary} plan={plan}")
        summary["plan"] = plan
        return summary

    for entry in plan:
        for duplicate_id, duplicate_name in zip(entry["duplicate_ids"], entry["duplicate_names"]):
            failed = False
            for table, owner_column in JUNCTIONS:
                try:
                    moved = await _repoint(table, owner_column, duplicate_id, entry["canonical_id"])
                    if table == "user_tags":
                        summary["repointed_user_tags"] += moved
                    else:
                        summary["repointed_opportunity_tags"] += moved
                except Exception:
                    failed = True
                    logger.exception(
                        f"TAG_DEDUP_REPOINT_FAILED: {table} tag={duplicate_id} -> {entry['canonical_id']}"
                    )

            if failed:
                logger.warning(f"TAG_DEDUP_KEPT: tag={duplicate_id} left in place (re-point incomplete)")
                continue

            try:
                await _delete_tag(duplicate_id)
                summary["deleted_tags"] += 1
                logger.info(
                    f"TAG_DEDUP_MERGED: '{duplicate_name}' -> '{entry['canonical_name']}' "
                    f"tag={duplicate_id}"
                )
            except Exception:
                logger.exception(f"TAG_DEDUP_DELETE_FAILED: tag={duplicate_id}")

    logger.info(f"TAG_DEDUP_DONE: {summary}")
    return summary