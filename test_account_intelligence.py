import pandas as pd

from account_intelligence import company_profile, portfolio_snapshot


def test_portfolio_snapshot_ranks_accounts_by_signal_strength():
    leads = pd.DataFrame(
        [
            {
                "firma": "Alpha Tech",
                "claim_score": 85,
                "need_score": 80,
                "verified_open_jobs": 4,
                "job_titles": "Servicetechniker | Elektroniker",
                "verified_job_titles": "Servicetechniker",
            },
            {
                "firma": "Beta Health",
                "claim_score": 60,
                "need_score": 50,
                "verified_open_jobs": 1,
                "job_titles": "Ergotherapeut",
                "verified_job_titles": "Ergotherapeut",
            },
        ]
    )
    jobs = pd.DataFrame(
        [
            {"firma": "Alpha Tech", "position": "Servicetechniker", "ort": "Hamburg"},
            {"firma": "Alpha Tech", "position": "Elektroniker", "ort": "Hamburg"},
            {"firma": "Beta Health", "position": "Ergotherapeut", "ort": "Berlin"},
        ]
    )
    evidence = pd.DataFrame(
        [
            {"firma": "Alpha Tech", "claim": "Neue Service-Standorte im Norden", "source": "Website"},
            {"firma": "Beta Health", "claim": "Expansion im Gesundheitsbereich", "source": "Presse"},
        ]
    )

    snapshot = portfolio_snapshot(leads, jobs, evidence, limit=5)
    assert list(snapshot.columns) == [
        "Firma",
        "Priorität",
        "Score",
        "Stellen",
        "Verifiziert",
        "Belege",
        "Hauptrollen",
        "Standorte",
        "Briefing",
    ]
    assert snapshot.iloc[0]["Firma"] == "Alpha Tech"


def test_company_profile_contains_actionable_signals():
    leads = pd.DataFrame(
        [{
            "firma": "Gamma Technik",
            "claim_score": 75,
            "need_score": 70,
            "verified_open_jobs": 3,
            "email": "hr@gammatechnik.de",
            "website": "https://gammatechnik.de",
            "job_titles": "Mechatroniker | Servicetechniker",
            "verified_job_titles": "Mechatroniker",
        }]
    )
    jobs = pd.DataFrame(
        [
            {"firma": "Gamma Technik", "position": "Mechatroniker", "ort": "Dortmund"},
            {"firma": "Gamma Technik", "position": "Servicetechniker", "ort": "Dortmund"},
        ]
    )
    evidence = pd.DataFrame(
        [{"firma": "Gamma Technik", "claim": "Standortausbau im Westen", "source": "Website"}]
    )

    profile = company_profile(leads, jobs, evidence, "Gamma Technik")
    assert profile["priority"] in {"Zeitnah", "Klärung"}
    assert profile["job_count"] == 2
    assert "Mechatroniker" in profile["job_titles"]
    assert profile["briefing"]
    assert profile["recommendations"]


if __name__ == "__main__":
    test_portfolio_snapshot_ranks_accounts_by_signal_strength()
    test_company_profile_contains_actionable_signals()
    print("account_intelligence tests passed")
