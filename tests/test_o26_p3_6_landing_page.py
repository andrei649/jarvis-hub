from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LANDING = ROOT / "marketing" / "landing" / "index.html"
SHOT_LIST = ROOT / "marketing" / "landing" / "demo-shot-list.md"
README = ROOT / "marketing" / "landing" / "README.md"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_landing_page_is_self_contained_static_html():
    html = _read(LANDING)

    assert "<style>" in html
    assert "<script" not in html.lower()
    assert "http://" not in html.lower()
    assert "https://" not in html.lower()
    assert "fetch(" not in html
    assert "xmlhttprequest" not in html.lower()
    assert "sendbeacon" not in html.lower()
    assert "url(" not in html.lower()


def test_landing_page_uses_brand_tokens_and_verified_copy():
    html = _read(LANDING)
    required = [
        "--void: #04070E",
        "--ink: #EEF1F5",
        "--accent: #2BB8F0",
        "--green: #41F59B",
        "--amber: #FFB23F",
        "--red: #FF5A52",
        "--violet: #A78BFA",
        "Space Grotesk",
        "JetBrains Mono",
        "Jarvis Hub",
        "The AI that works while you sleep",
        "local-first personal AI operating system",
        "17 specialist agents",
        "governed autonomy",
        "approval queue",
        "tamper-evident audit log",
        "living memory",
        "$0/month",
    ]

    for needle in required:
        assert needle in html

    stale_claims = ("2,150", "2,400", "99% SP", "1,119-SP", "3,600+",
                    "Demo capture support", "demo-shot-list.md")
    for stale in stale_claims:
        assert stale not in html


def test_demo_shot_list_matches_teaser_pack_owner_scope():
    shot_list = _read(SHOT_LIST)
    shots = [
        "Hero cockpit at rest",
        "Trust Center",
        "Governed-autonomy moment",
        "Morning brief",
        "Frigga strict-local badge",
        "WorldView globe",
    ]

    for shot in shots:
        assert shot in shot_list

    assert "Owner records the actual footage in M4" in shot_list
    assert "Demo mode must be clearly badged" in shot_list


def test_landing_readme_documents_no_external_calls_contract():
    readme = _read(README)

    assert "Open `index.html` directly" in readme
    assert "No external scripts, stylesheets, fonts, images, or API calls" in readme
    assert "docs/marketing/TEASER_PACK.md" in readme
    assert "docs/BRAND_BOOK.md" in readme
