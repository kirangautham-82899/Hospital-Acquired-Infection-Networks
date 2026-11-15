"""Runs app/app.py headlessly with Streamlit's AppTest and clicks through every
control, checking that no setting raises an error or prints 'nan'."""
import itertools

import pytest

import config

AppTest = pytest.importorskip("streamlit.testing.v1").AppTest
APP = str(config.ROOT_DIR / "app" / "app.py")


def _texts(at):
    return " ".join(i.value for i in at.info)


def test_app_loads_without_errors():
    at = AppTest.from_file(APP, default_timeout=60).run()
    assert not at.exception
    assert len(at.tabs) == 4
    assert "nan" not in _texts(at).lower()


@pytest.mark.parametrize("ward", config.APP_REAL_WARDS)
def test_what_if_every_ward(ward):
    at = AppTest.from_file(APP, default_timeout=60).run()
    at.selectbox(key="whatif_ward").set_value(ward).run()
    assert not at.exception
    assert ward in _texts(at)


def test_intervention_every_setting():
    at = AppTest.from_file(APP, default_timeout=60).run()
    for k, r in itertools.product(config.INTERVENTION_K_VALUES, config.INTERVENTION_REDUCTIONS):
        at.radio[0].set_value(k)
        at.radio[1].set_value(r)
        at.run()
        assert not at.exception, (k, r)
        assert "nan" not in _texts(at).lower(), (k, r)
