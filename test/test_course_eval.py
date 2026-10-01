"""Course-label harness (ADR-0016 slice 1a) on synthetic label sets: the label-file
reader, exclusions, the seeded venue split, item-weighted per-course precision, the
readability floor, coverage over passing courses, the winner rule and the CLI."""

from __future__ import annotations

import json
from dataclasses import replace
from typing import TYPE_CHECKING, Any

import pytest

from apps.menu_pipeline import course_eval as cli
from packages.helios_parsing.course_eval import (
    MIN_SECTIONS,
    MIN_VENUES,
    LabelSetError,
    Manifest,
    Prediction,
    Section,
    check_label_set,
    disagreements,
    draw_label_set,
    exclusion_ids,
    exclusions_digest,
    predictions_of,
    sample_venues,
    score,
    section,
    split_of,
    winner,
)

if TYPE_CHECKING:
    from pathlib import Path

RAW = {
    "venue": "gers-a",
    "version_id": 4711,
    "section_key": "v4711:b0012:tacos",
    "name": "Tacos",
    "name_path": ["Tacos"],
    "items": ["Al Pastor", "Carnitas"],
    "priced_items": 7,
    "split": "test",
    "agent_label": "entree",
    "label": "entree",
    "labeller": "agent:test",
    "owner_confirmed": False,
}


def _manifest(seed: int = 1, excluded: frozenset[str] = frozenset(), **kw: Any) -> Manifest:
    fields: dict[str, Any] = {
        "set": "synthetic",
        "seed": seed,
        "venues": 120,
        "sampled_venues": 120,
        "test_share": 0.4,
        "exclusions_sha256": exclusions_digest(excluded),
        "excluded_venues": len(excluded),
        "guide": "course-guide-v1",
        "method_version": "m",
        "unsectioned_priced_items": None,
        **kw,
    }
    return Manifest(**fields)


_keys = iter(range(1, 1_000_000))


def _row(
    venue: str,
    label: str | None,
    *,
    priced: int = 10,
    split: str = "test",
    agent: str | None = None,
    confirmed: bool = False,
) -> Section:
    n = next(_keys)
    agent_label = agent or label
    return Section(
        venue=venue,
        version_id=n,
        section_key=f"v{n}:b0001:s{n}",
        name=f"Section {n}",
        name_path=(f"Section {n}",),
        items=("Dish",),
        priced_items=priced,
        split=split,  # type: ignore[arg-type]
        agent_label=agent_label,
        label=label,
        labeller="agent:test" if agent_label else None,
        owner_confirmed=confirmed,
    )


def _arm(rows: list[Section], courses: list[str | None]) -> dict[str, Prediction]:
    return {
        r.section_key: Prediction(r.section_key, c, None)
        for r, c in zip(rows, courses, strict=True)
    }


# --- label-file reader -------------------------------------------------------------------


def test_section_reads_a_label_row_and_a_candidate() -> None:
    row = section(RAW)
    assert row.label == "entree" and row.name_path == ("Tacos",) and row.priced_items == 7
    candidate = section(
        {k: v for k, v in RAW.items() if k not in {"split", "agent_label", "label", "labeller"}}
    )
    assert candidate.split is None and candidate.label is None and not candidate.owner_confirmed
    assert section({**RAW, "name_path": None}).name_path == ("Tacos",)
    assert section(RAW).to_json() == RAW


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ({"label": "mains"}, "not one of the 9 courses"),
        ({"agent_label": "abstain"}, "not one of the 9 courses"),
        ({"section_key": "v1:b0012:tacos"}, "not a native key of Version 4711"),
        ({"split": "dev"}, "not train/test"),
        ({"priced_items": -1}, "negative priced_items"),
        ({"name": "  "}, "empty venue or section name"),
        ({"agent_label": None}, "without the agent's blind label"),
        ({"labeller": None}, "needs a final label and a labeller"),
        ({"label": None}, "needs a final label and a labeller"),
        ({"version_id": "x"}, "malformed row"),
    ],
)
def test_section_refuses_malformed_rows(change: dict[str, Any], message: str) -> None:
    with pytest.raises(LabelSetError, match=message):
        section({**RAW, **change})


def test_section_refuses_a_missing_field() -> None:
    with pytest.raises(LabelSetError, match="malformed row"):
        section({k: v for k, v in RAW.items() if k != "items"})


# --- exclusions, sampling and the split ---------------------------------------------------


def test_exclusion_file_and_digest() -> None:
    ids = exclusion_ids(["# P5-5 held-out venues", "gers-b", "", "  gers-a  # note", "gers-b"])
    assert ids == {"gers-a", "gers-b"}
    assert exclusions_digest(ids) == exclusions_digest(["gers-b", "gers-a"])
    assert exclusions_digest(ids) != exclusions_digest(["gers-a"])


def test_split_is_seeded_per_venue_and_near_the_share() -> None:
    venues = [f"gers-{i}" for i in range(4000)]
    splits = [split_of(7, v) for v in venues]
    assert splits == [split_of(7, v) for v in venues]  # deterministic
    assert 0.37 < splits.count("test") / len(venues) < 0.43
    assert [split_of(8, v) for v in venues] != splits  # the seed matters
    assert {split_of(7, v, 0.0) for v in venues} == {"train"}
    assert {split_of(7, v, 1.0) for v in venues} == {"test"}


def test_sample_never_draws_an_excluded_venue() -> None:
    eligible = [f"gers-{i}" for i in range(50)]
    excluded = frozenset(f"gers-{i}" for i in range(0, 50, 2))
    chosen = sample_venues(eligible, excluded, seed=3, n=10)
    assert len(chosen) == 10 and not set(chosen) & excluded
    assert chosen == sample_venues(reversed(eligible), excluded, seed=3, n=10)
    assert sample_venues(eligible, excluded, seed=3, n=999) == sorted(set(eligible) - excluded)


def test_draw_label_set_records_the_split_and_manifest() -> None:
    candidates = [
        Section(f"gers-{v}", v, f"v{v}:b{s}:x", f"S{s}", (f"S{s}",), ("Dish",), s)
        for v in range(30)
        for s in range(3)
    ]
    excluded = frozenset({"gers-0", "gers-1", "outside"})
    manifest, rows = draw_label_set(
        candidates,
        excluded,
        set_name="set-1",
        seed=11,
        venues=12,
        method_version="m1",
        unsectioned={"gers-5": 4, "gers-0": 9},
    )
    venues = {r.venue for r in rows}
    assert len(venues) == 12 and not venues & excluded and len(rows) == 36
    assert all(r.split == split_of(11, r.venue) and r.label is None for r in rows)
    assert manifest.sampled_venues == 12 and manifest.excluded_venues == 3
    assert manifest.exclusions_sha256 == exclusions_digest(excluded)
    assert manifest.guide == "course-guide-v1" and manifest.method_version == "m1"
    assert set(manifest.unsectioned_priced_items or {}) == venues  # only sampled venues
    assert Manifest.from_json(json.loads(json.dumps(manifest.to_json()))) == manifest
    check_label_set(manifest, rows, excluded)

    with pytest.raises(LabelSetError, match="appears twice"):
        draw_label_set(
            [candidates[0], candidates[0]],
            excluded,
            set_name="x",
            seed=1,
            venues=1,
            method_version="m",
        )


def test_check_label_set_refuses_exclusions_moved_splits_and_duplicates() -> None:
    excluded = frozenset({"gers-held-out"})
    manifest = _manifest(seed=5, excluded=excluded)
    venue = "gers-a"
    row = _row(venue, "entree", split=split_of(5, venue))
    check_label_set(manifest, [row], excluded)

    with pytest.raises(LabelSetError, match="exclusion list differs"):
        check_label_set(manifest, [row], frozenset())
    held_out = _row("gers-held-out", "entree", split=split_of(5, "gers-held-out"))
    with pytest.raises(LabelSetError, match="is on the exclusion list"):
        check_label_set(manifest, [row, held_out], excluded)
    moved = _row(venue, "entree", split="train" if row.split == "test" else "test")
    with pytest.raises(LabelSetError, match="not the venue's seeded split"):
        check_label_set(manifest, [moved], excluded)
    with pytest.raises(LabelSetError, match="appears twice"):
        check_label_set(manifest, [row, row], excluded)


# --- predictions and owner review ---------------------------------------------------------


def test_predictions_name_one_labeller_and_each_section_once() -> None:
    labeller, arm = predictions_of(
        [
            {"section_key": "v1:a", "course": "dessert", "confidence": 0.9, "labeller": "lex"},
            {"section_key": "v1:b", "course": None, "labeller": "lex"},
        ]
    )
    assert labeller == "lex" and arm["v1:b"].course is None and arm["v1:a"].confidence == 0.9
    with pytest.raises(LabelSetError, match="2 labellers"):
        predictions_of(
            [{"section_key": "a", "labeller": "x"}, {"section_key": "b", "labeller": "y"}]
        )
    with pytest.raises(LabelSetError, match="predicted twice"):
        predictions_of([{"section_key": "a", "labeller": "x"}] * 2)
    with pytest.raises(LabelSetError, match="not one of"):
        predictions_of([{"section_key": "a", "labeller": "x", "course": "snack"}])
    with pytest.raises(LabelSetError, match="missing"):
        predictions_of([{"course": "side", "labeller": "x"}])


def test_disagreements_skip_abstentions_confirmed_rows_and_other_splits() -> None:
    agree, differ, abstained, confirmed = (_row(f"g{i}", "entree") for i in range(4))
    confirmed = replace(confirmed, owner_confirmed=True)
    train = _row("g9", "entree", split="train")
    rows = [agree, differ, abstained, confirmed, train]
    lexicon = _arm(rows, ["entree", "entree", None, "side", "side"])
    model = _arm(rows, ["entree", "appetizer", None, "side", "side"])
    pending = disagreements(rows, [lexicon, model])
    assert [(r.section_key, p) for r, p in pending] == [
        (differ.section_key, ("entree", "appetizer"))
    ]
    assert [r.section_key for r, _ in disagreements(rows, [lexicon], "train")] == [
        train.section_key
    ]


# --- scoring ------------------------------------------------------------------------------


def _scored_set() -> tuple[list[Section], list[str | None]]:
    """Test rows and one arm's predictions, one course per situation the gate must read."""
    rows: list[Section] = []
    predicted: list[str | None] = []

    def add(row: Section, course: str | None) -> None:
        rows.append(row)
        predicted.append(course)

    # entree: 24 sections at 12 venues; one is really an appetizer -> 230/240 = 0.958 passes
    for i in range(24):
        if i == 0:
            add(_row(f"v{i % 12}", "appetizer", confirmed=True), "entree")
        else:
            add(_row(f"v{i % 12}", "entree"), "entree")
    # drink: 24 sections at 12 venues; two are alcohol (one the owner changed) -> 0.917 fails
    for i in range(24):
        if i == 0:
            add(_row(f"v{i % 12}", "alcohol", agent="drink", confirmed=True), "drink")
        elif i == 1:
            add(_row(f"v{i % 12}", "alcohol", confirmed=True), "drink")
        else:
            add(_row(f"v{i % 12}", "drink"), "drink")
    # dessert: perfect but too thin to read (5 sections, 5 venues)
    for i in range(5):
        add(_row(f"v{i}", "dessert"), "dessert")
    # abstained and other
    add(_row("v1", "side", priced=20), None)
    add(_row("v2", "other", priced=6), "other")
    # a train row never counts
    add(_row("v99", "entree", split="train"), "dessert")
    return rows, predicted


def test_score_weights_items_and_gates_each_course() -> None:
    rows, predicted = _scored_set()
    # unsectioned items count for test venues only
    test_venue = next(f"u{i}" for i in range(100) if split_of(1, f"u{i}") == "test")
    train_venue = next(f"u{i}" for i in range(100) if split_of(1, f"u{i}") == "train")
    report = score(
        _manifest(unsectioned_priced_items={test_venue: 5, train_venue: 1000}),
        rows,
        "lexicon@abc",
        _arm(rows, predicted),
    )
    total = 240 + 240 + 50 + 20 + 6
    assert report["test_sections"] == 55 and report["test_items"] == total
    entree, drink, dessert = (report["courses"][c] for c in ("entree", "drink", "dessert"))
    assert (entree["predicted_items"], entree["correct_items"]) == (240, 230)
    assert entree["predicted_venues"] == 12 and entree["readable"] and entree["passes"]
    assert drink["precision"] == pytest.approx(220 / 240) and not drink["passes"]
    assert dessert["precision"] == 1.0 and not dessert["readable"] and not dessert["passes"]
    assert report["courses"]["side"]["precision"] is None
    assert report["courses"]["alcohol"]["labelled_items"] == 20
    assert "other" not in report["courses"]  # never an index row
    assert report["passing"] == ["entree"]
    assert report["covered_items"] == 240 and report["coverage"] == pytest.approx(240 / total)
    assert report["section_accuracy"] == pytest.approx((23 + 22 + 5 + 1) / 55)
    assert report["abstain_rate"] == {"items": pytest.approx(20 / total), "sections": 1 / 55}
    assert report["other_rate"]["items"] == pytest.approx(6 / total)
    assert report["confusion_items"]["alcohol"] == {"drink": 20}
    assert report["confusion_sections"]["side"] == {"abstain": 1}
    assert report["owner_review"] == {"confirmed": 3, "changed": 1}
    assert report["unsectioned_share"] == pytest.approx(5 / (total + 5))
    assert "markdown" not in report and "| `entree` | 240 | 230 | 0.958" in cli.markdown(report)


def test_gate_boundaries() -> None:
    def course_report(sections: int, venues: int, wrong: int) -> dict[str, Any]:
        rows = [
            _row(f"v{i % venues}", "kids" if i >= wrong else "entree", confirmed=i < wrong)
            for i in range(sections)
        ]
        courses: dict[str, dict[str, Any]] = score(
            _manifest(), rows, "arm", _arm(rows, ["kids"] * sections)
        )["courses"]
        return courses["kids"]

    exactly = course_report(MIN_SECTIONS, MIN_VENUES, wrong=1)  # 19/20 = 0.95
    assert exactly["precision"] == pytest.approx(0.95) and exactly["passes"]
    assert not course_report(MIN_SECTIONS - 1, MIN_VENUES, 0)["readable"]
    assert not course_report(MIN_SECTIONS, MIN_VENUES - 1, 0)["readable"]
    assert not course_report(MIN_SECTIONS, MIN_VENUES, wrong=2)["passes"]


def test_score_refuses_an_incomplete_or_unreviewed_set() -> None:
    rows, predicted = _scored_set()
    arm = _arm(rows, predicted)
    manifest = _manifest()
    with pytest.raises(LabelSetError, match="1 test sections have no prediction"):
        score(manifest, rows, "a", {k: v for k, v in arm.items() if k != rows[0].section_key})
    with pytest.raises(LabelSetError, match="not in the set"):
        score(manifest, rows, "a", {**arm, "v0:zz": Prediction("v0:zz", None, None)})
    unlabelled = [*rows, _row("v3", None)]
    with pytest.raises(LabelSetError, match="1 test sections have no label"):
        score(manifest, unlabelled, "a", _arm(unlabelled, [*predicted, None]))
    unreviewed = [*rows, _row("v3", "side")]
    with pytest.raises(LabelSetError, match="1 disagreements await"):
        score(manifest, unreviewed, "a", _arm(unreviewed, [*predicted, "entree"]))


def test_winner_rule() -> None:
    def report(name: str, covered: int, passing: list[str], split: str = "s") -> dict[str, Any]:
        return {
            "labeller": name,
            "covered_items": covered,
            "passing": passing,
            "test_set_sha256": split,
        }

    assert winner(report("lex", 100, ["entree"]), report("lr", 101, ["entree"])) == "lr"
    assert winner(report("lex", 100, ["entree"]), report("lr", 100, ["drink"])) == "lex"  # tie
    assert winner(report("lex", 120, ["entree"]), report("lr", 100, ["entree"])) == "lex"
    assert winner(report("lex", 0, []), report("lr", 50, ["kids"])) == "lr"
    assert winner(report("lex", 0, []), report("lr", 0, [])) is None
    with pytest.raises(LabelSetError, match="different test splits"):
        winner(report("lex", 1, ["entree"]), report("lr", 1, ["entree"], split="other"))


# --- CLI ----------------------------------------------------------------------------------


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> Path:
    path.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    return path


def test_cli_samples_reviews_scores_and_compares(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    candidates = [
        Section(f"gers-{v}", v, f"v{v}:b{s}:x", f"S{s}", ("Menu", f"S{s}"), ("Dish",), 2).to_json()
        for v in range(1, 9)
        for s in range(2)
    ]
    held_out = tmp_path / "held-out.txt"
    held_out.write_text("# P5-5\ngers-1\ngers-2\n", encoding="utf-8")
    common = ["--exclude", str(held_out)]
    sample_args = [
        "sample",
        "--candidates",
        str(_write_jsonl(tmp_path / "candidates.jsonl", candidates)),
        *common,
        "--set",
        "set-1",
        "--seed",
        "4",
        "--venues",
        "5",
        "--method-version",
        "m",
        "--root",
        str(tmp_path),
    ]
    assert cli.main(sample_args) == 0
    assert "set-1: venues=5 sections=10" in capsys.readouterr().out
    assert cli.main(sample_args) == 2  # a drawn split never moves
    assert "already holds a label set" in capsys.readouterr().err

    labels = tmp_path / "set-1"
    rows = list(cli.read_jsonl(labels / "sections.jsonl"))
    assert not {r["venue"] for r in rows} & {"gers-1", "gers-2"}
    for r in rows:
        r.update(agent_label="entree", label="entree", labeller="agent:t")
    _write_jsonl(labels / "sections.jsonl", rows)
    test_keys = [r["section_key"] for r in rows if r["split"] == "test"]
    assert test_keys  # seed 4 puts at least one sampled venue in test

    def predictions(name: str, course: str | None, first: str | None) -> Path:
        out = [{"section_key": r["section_key"], "course": course, "labeller": name} for r in rows]
        out[[r["section_key"] for r in rows].index(test_keys[0])]["course"] = first
        return _write_jsonl(tmp_path / f"{name}.jsonl", out)

    lexicon, model = predictions("lex", "entree", "side"), predictions("lr", None, None)
    review = ["disagreements", "--labels", str(labels), *common, str(lexicon), str(model)]
    assert cli.main(review) == 0
    out = capsys.readouterr().out
    assert out.startswith("1 test sections to review") and "agent=entree\tarms=side abstain" in out

    report = tmp_path / "lex.json"
    scoring = ["score", "--labels", str(labels), *common, "--out", str(report), str(lexicon)]
    assert cli.main(scoring) == 2
    assert "1 disagreements await" in capsys.readouterr().err
    other_list = tmp_path / "other.txt"
    other_list.write_text("gers-1\n", encoding="utf-8")
    assert (
        cli.main(["score", "--labels", str(labels), "--exclude", str(other_list), str(lexicon)])
        == 2
    )
    assert "exclusion list differs" in capsys.readouterr().err

    for r in rows:
        if r["section_key"] == test_keys[0]:
            r["owner_confirmed"] = True
    _write_jsonl(labels / "sections.jsonl", rows)
    assert cli.main(scoring) == 0
    assert "| `entree` |" in capsys.readouterr().out
    assert json.loads(report.read_text(encoding="utf-8"))["owner_review"]["confirmed"] == 1
    model_report = tmp_path / "lr.json"
    assert cli.main([*scoring[:-3], "--out", str(model_report), str(model)]) == 0
    capsys.readouterr()
    assert cli.main(["compare", str(report), str(model_report)]) == 0
    assert "winner: none (no arm passes any course)" in capsys.readouterr().out
