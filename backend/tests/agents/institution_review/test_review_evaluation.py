def test_bad_evidence_does_not_score_as_success():
    from app.agents.institution_review.evaluation import evaluate_case

    scores = evaluate_case(
        {"finding_count": 0, "unsupported_findings": 0},
        {"finding_count": 1, "unsupported_findings": 1},
    )
    assert all(score["value"] == 0 for score in scores)


def test_fixture_categories_use_business_enum_values():
    import json
    from pathlib import Path

    cases = json.loads(
        (Path(__file__).parents[2] / "fixtures/langfuse/standard_review_cases.json").read_text(
            encoding="utf-8"
        )
    )
    assert cases[0]["expected"]["categories"] == ["conflict"]
    assert cases[1]["expected"]["categories"] == ["duplicate"]
