import pytest
import state

@pytest.fixture
def db(tmp_path, monkeypatch):
    monkeypatch.setattr(state, "DB_PATH", tmp_path / "test.db")
    state.init_db()
    return state
