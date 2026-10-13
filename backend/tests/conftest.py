import os

os.environ["DATABASE_URL"] = "sqlite://"
os.environ["JWT_SECRET"] = "test-secret-test-secret-test-secret-123"
os.environ["FERNET_KEY"] = "ZmDfcTF7_60GrrY167zsiPd67pEvs0aGOv2oasOM1Pg="  # test-only key

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

from app.core.db import get_db  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Base  # noqa: E402


@pytest.fixture()
def db_session():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    with sessionmaker(bind=engine, expire_on_commit=False)() as s:
        yield s


@pytest.fixture()
def client(db_session):
    app.dependency_overrides[get_db] = lambda: db_session
    yield TestClient(app)
    app.dependency_overrides.clear()


# ---- Playwright fixtures (local HTML only; real sites are never contacted) ----------------
import os  # noqa: E402
from pathlib import Path  # noqa: E402

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(scope="session")
def browser():
    pw_mod = pytest.importorskip("playwright.sync_api")
    pw = pw_mod.sync_playwright().start()
    exe = os.environ.get("PLAYWRIGHT_CHROMIUM_EXECUTABLE")
    try:
        b = pw.chromium.launch(executable_path=exe) if exe else pw.chromium.launch()
    except Exception as e:  # browser binaries not installed
        pw.stop()
        pytest.skip(f"chromium not available: {e}")
    yield b
    b.close()
    pw.stop()


@pytest.fixture()
def page(browser):
    ctx = browser.new_context()
    pg = ctx.new_page()
    pg.set_default_timeout(4000)
    yield pg
    ctx.close()


def serve(page, routes: dict[str, str]):
    """Fulfil requests whose URL contains a key with the given fixture file / HTML string."""

    def handler(route):
        url = route.request.url
        for key, body in routes.items():
            if key in url:
                html = (FIXTURES / body).read_text() if body.endswith(".html") else body
                return route.fulfill(status=200, content_type="text/html", body=html)
        route.fulfill(status=404, body="not found")

    page.route("**/*", handler)
