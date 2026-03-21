import json
import tempfile
from pathlib import Path

from agent_trader.utils.project_state import reset_project_state


def test_reset_project_state_clears_profile_root_and_rewrites_profile_metadata(monkeypatch):
    with tempfile.TemporaryDirectory(dir=".", ignore_cleanup_errors=True) as temp_dir:
        root = Path(temp_dir).resolve()
        profile_root = root / "data" / "profiles" / "claude"
        docs_root = root / "docs"
        (profile_root / "research").mkdir(parents=True)
        (profile_root / "research" / "latest.json").write_text("{}", encoding="utf-8")
        (profile_root / "portfolio_state.json").write_text("{}", encoding="utf-8")
        (docs_root / "data").mkdir(parents=True)
        (docs_root / "data" / "dashboard.json").write_text("{}", encoding="utf-8")
        (docs_root / "index.html").write_text("<html></html>", encoding="utf-8")

        monkeypatch.setenv("AGENT_PROFILE", "claude")
        monkeypatch.setenv("AGENT_LABEL", "Claude Strategist")
        monkeypatch.setenv("DATA_DIR", str(profile_root))

        summary = reset_project_state(
            data_dir=str(profile_root),
            docs_dir=str(docs_root),
            include_docs=True,
        )

        assert summary["include_docs"] is True
        assert (profile_root / "profile.json").exists()
        assert not (profile_root / "research").exists()
        assert not (profile_root / "portfolio_state.json").exists()
        assert not (docs_root / "data").exists()
        assert not (docs_root / "index.html").exists()

        metadata = json.loads((profile_root / "profile.json").read_text(encoding="utf-8"))
        assert metadata["id"] == "claude"
        assert metadata["label"] == "Claude Strategist"
        assert metadata["data_dir"] == profile_root.as_posix()


def test_reset_project_state_clears_all_profiles_and_top_level_generated_data():
    with tempfile.TemporaryDirectory(dir=".", ignore_cleanup_errors=True) as temp_dir:
        root = Path(temp_dir).resolve()
        data_root = root / "data"
        docs_root = root / "docs"

        (data_root / "profiles" / "claude" / "research").mkdir(parents=True)
        (data_root / "profiles" / "codex" / "research").mkdir(parents=True)
        (data_root / "context").mkdir(parents=True)
        (data_root / "context" / "latest_research.json").write_text("{}", encoding="utf-8")
        (data_root / "news_collection_20260321_1449.md").write_text("notes", encoding="utf-8")
        (docs_root / "data").mkdir(parents=True)
        (docs_root / "index.html").write_text("<html></html>", encoding="utf-8")

        summary = reset_project_state(
            data_dir=str(data_root),
            docs_dir=str(docs_root),
            all_profiles=True,
            include_docs=True,
        )

        assert summary["all_profiles"] is True
        assert not (data_root / "profiles").exists()
        assert not (data_root / "context").exists()
        assert not (data_root / "news_collection_20260321_1449.md").exists()
        assert not (docs_root / "data").exists()
        assert not (docs_root / "index.html").exists()
