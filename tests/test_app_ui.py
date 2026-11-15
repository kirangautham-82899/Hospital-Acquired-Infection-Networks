"""Runs app/app.py headlessly with Streamlit's AppTest: opens every chapter from
the sidebar, uses every control, and checks nothing raises or prints 'nan'.

(The app was restructured from tabs into sidebar chapters; the intervention
controls now live in the embedded scene, whose numbers tests/test_demo_data.py
checks against the P10 tables.)"""
import pytest

import config

AppTest = pytest.importorskip("streamlit.testing.v1").AppTest
APP = str(config.ROOT_DIR / "app" / "app.py")
N_CHAPTERS = 8


def _texts(at):
    return " ".join(i.value for i in at.info) + " " + " ".join(m.value for m in at.markdown)


def _open(chapter):
    at = AppTest.from_file(APP, default_timeout=60).run()
    at.sidebar.radio(key="chapter").set_value(chapter).run()
    return at


def test_app_loads_on_first_chapter():
    at = AppTest.from_file(APP, default_timeout=60).run()
    assert not at.exception
    assert len(at.sidebar.radio(key="chapter").options) == N_CHAPTERS
    assert "Chapter 01" in _texts(at)


@pytest.mark.parametrize("chapter", range(N_CHAPTERS))
def test_every_chapter_renders(chapter):
    at = _open(chapter)
    assert not at.exception, chapter
    assert f"Chapter {chapter + 1:02d}" in _texts(at)
    assert "nan" not in _texts(at).lower(), chapter


def test_next_button_moves_on():
    at = AppTest.from_file(APP, default_timeout=60).run()
    at.button(key="next").click().run()
    assert at.sidebar.radio(key="chapter").value == 1


@pytest.mark.parametrize("ward", config.APP_REAL_WARDS)
def test_what_if_every_ward(ward):
    at = _open(4)  # "What if"
    at.selectbox(key="whatif_ward").set_value(ward).run()
    assert not at.exception
    assert ward in _texts(at)
