# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""Tests for the canonical-module identity guard (T-20260913-312928799).

Why this guard exists: a module name is not proof. `web-scraper` on PyPI is a
foreign package (web_scraper 1.0, Vahid Vaezian, 2018-08-10) that occupies the same
import name, and BACH asked for it by name until 611c1a1. Pinning the git source
fixed resolution for new installs; it does nothing for a machine that already has the
foreign package. This guard closes that at runtime.

The foreign package's real shape is used here, not an invented one: its
`web_scraper/__init__.py` exports exactly three functions and no `WebScraper` at all
(read from the sdist on PyPI, 2026-09-13).
"""

import sys
import types
from pathlib import Path

import pytest

SYSTEM_ROOT = Path(__file__).parent.parent
if str(SYSTEM_ROOT) not in sys.path:
    sys.path.insert(0, str(SYSTEM_ROOT))

from hub import canonical_seam  # noqa: E402
from hub.canonical_seam import CanonicalSeam, require_canonical  # noqa: E402


class Unavailable(RuntimeError):
    """Stand-in for a seam's own exception type."""


def make_seam(**overrides):
    base = dict(
        module="stub_canonical_module",
        attribute="WebScraper",
        distribution="web-scraper",
        repo_url="github.com/ellmos-ai/web-scraper",
        params=("timeout", "max_bytes", "max_redirects"),
        operations=("get", "headers"),
        env_var="BACH_WEB_SCRAPE_ENGINE",
        canonical_value="canonical",
        bundled_value="bundled",
        error=Unavailable,
    )
    base.update(overrides)
    return CanonicalSeam(**base)


def install(monkeypatch, name, module):
    monkeypatch.setitem(sys.modules, name, module)


def good_module(name="stub_canonical_module"):
    """A module shaped like ours."""
    module = types.ModuleType(name)

    class WebScraper:
        def __init__(self, timeout=20, max_bytes=5_000_000, max_redirects=10,
                     user_agent="", verify_ssl=True, allow_private=False):
            pass

        def get(self, url):
            return {}

        def headers(self, url):
            return {}

    module.WebScraper = WebScraper
    return module


@pytest.fixture(autouse=True)
def no_real_metadata(monkeypatch):
    """Default: no distribution metadata, like a clone on PYTHONPATH.

    Tests that care about metadata override this explicitly.
    """
    monkeypatch.setattr(canonical_seam, "_declared_urls", lambda _name: ())


# --- the case this guard was built for ------------------------------------------------

def test_the_real_foreign_package_shape_is_rejected_with_a_remedy(monkeypatch):
    """The 2018 PyPI package: same import name, three functions, no WebScraper."""
    foreign = types.ModuleType("stub_canonical_module")
    foreign.get_links_directly = lambda *a, **k: None
    foreign.get_links_using_Google_search = lambda *a, **k: None
    foreign.find_links_by_extension = lambda *a, **k: None
    install(monkeypatch, "stub_canonical_module", foreign)

    with pytest.raises(Unavailable) as excinfo:
        require_canonical(make_seam())

    message = str(excinfo.value)
    assert "FREMDES Paket" in message
    assert "pip uninstall -y web-scraper" in message, "the message must be actionable"
    assert "KEIN Rueckfall" in message, "the fail-closed contract must be restated"


def test_a_version_without_max_redirects_is_rejected_by_name(monkeypatch):
    """The realistic skew: an older build of our OWN module.

    Without `max_redirects` this handler's redirect limit silently becomes the
    module's own -- exactly the relaxation that blocked the default switch until
    web-scraper PR #2. It must not pass unnoticed.
    """
    module = types.ModuleType("stub_canonical_module")

    class Old:
        def __init__(self, timeout=20, max_bytes=1):
            pass

        def get(self, url):
            return {}

        def headers(self, url):
            return {}

    module.WebScraper = Old
    install(monkeypatch, "stub_canonical_module", module)

    with pytest.raises(Unavailable) as excinfo:
        require_canonical(make_seam())

    assert "max_redirects" in str(excinfo.value), "the missing parameter must be named"


def test_a_missing_operation_is_rejected_by_name(monkeypatch):
    module = good_module()
    del module.WebScraper.headers
    install(monkeypatch, "stub_canonical_module", module)

    with pytest.raises(Unavailable) as excinfo:
        require_canonical(make_seam())

    assert "headers" in str(excinfo.value)


# --- the metadata signal: a counter-proof, never a requirement -------------------------

def test_metadata_pointing_at_another_repository_is_rejected(monkeypatch):
    """A package that declares where it comes from, and it is not us."""
    install(monkeypatch, "stub_canonical_module", good_module())
    monkeypatch.setattr(
        canonical_seam, "_declared_urls",
        lambda _name: ("https://github.com/vvaezian/Web-Scraper",),
    )

    with pytest.raises(Unavailable) as excinfo:
        require_canonical(make_seam())

    message = str(excinfo.value)
    assert "vvaezian" in message, "say what was actually found"
    assert "github.com/ellmos-ai/web-scraper" in message, "and what was expected"


def test_a_distribution_without_urls_is_not_treated_as_foreign(monkeypatch):
    """`doc-services` 0.1.0 declares no URLs, and a PYTHONPATH clone has no metadata.

    Turning a missing field into an accusation would break legitimate setups. The
    interface check is the mandatory signal; metadata only ever disproves.
    """
    install(monkeypatch, "stub_canonical_module", good_module())
    monkeypatch.setattr(canonical_seam, "_declared_urls", lambda _name: ())

    assert require_canonical(make_seam()) is sys.modules["stub_canonical_module"].WebScraper


def test_url_case_does_not_decide_identity(monkeypatch):
    """Hosts are case-insensitive; a capitalised URL is not a foreign package."""
    install(monkeypatch, "stub_canonical_module", good_module())
    monkeypatch.setattr(
        canonical_seam, "_declared_urls",
        lambda _name: ("https://GitHub.com/ellmos-AI/Web-Scraper",),
    )

    assert require_canonical(make_seam(repo_url="github.com/ellmos-ai/web-scraper"))


def test_our_own_urls_are_accepted(monkeypatch):
    install(monkeypatch, "stub_canonical_module", good_module())
    monkeypatch.setattr(
        canonical_seam, "_declared_urls",
        lambda _name: ("Homepage, https://github.com/ellmos-ai/web-scraper",),
    )

    assert require_canonical(make_seam()) is not None


# --- a module that is not importable at all -------------------------------------------

def test_an_unimportable_module_keeps_the_old_wording(monkeypatch):
    """The existing contract: name the switch and the way back."""
    install(monkeypatch, "stub_canonical_module", None)  # forces ImportError

    with pytest.raises(Unavailable) as excinfo:
        require_canonical(make_seam())

    message = str(excinfo.value)
    assert "BACH_WEB_SCRAPE_ENGINE" in message
    assert "bundled" in message


# --- the real module, if it is installed ----------------------------------------------

def test_the_real_web_scraper_passes_the_guard():
    """No amount of stubbing replaces running it against the actual module."""
    pytest.importorskip("web_scraper")
    from hub.web_scrape import CANONICAL_SEAM

    scraper_cls = require_canonical(CANONICAL_SEAM)
    assert scraper_cls.__name__ == "WebScraper"


def test_the_doc_services_seam_uses_the_same_guard(monkeypatch):
    """One function, two seams -- and it rejects a build without `produces`.

    That parameter is not cosmetic: without it the module returns markdown, which
    measured 8.698 instead of 14.856 words on a real paper because word boundaries
    collapse. A silent quality loss is worse than a named failure.
    """
    from hub._services.document.pdf_service import DOC_CANONICAL_SEAM

    module = types.ModuleType("doc_services")
    module.extrahieren = lambda pfad: None  # no `produces`
    install(monkeypatch, "doc_services", module)

    with pytest.raises(DOC_CANONICAL_SEAM.error) as excinfo:
        require_canonical(DOC_CANONICAL_SEAM)

    assert "produces" in str(excinfo.value)
