import pytest

from oribrink.config import Config
from oribrink.storage import Storage


@pytest.fixture()
def storage():
    st = Storage(":memory:")
    yield st
    st.close()


@pytest.fixture()
def cfg():
    return Config()
