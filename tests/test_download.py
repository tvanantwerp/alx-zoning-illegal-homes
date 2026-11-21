"""Paged ArcGIS downloads preserve the previous cache on an invalid page."""
from unittest.mock import Mock

import pytest

from alx_zoning_illegal_homes.downloader import download


def test_invalid_second_page_preserves_cached_layer(tmp_path, monkeypatch):
    destination = tmp_path / "paving.geojson"
    destination.write_text("previous export")

    def get_page(url, params, timeout):
        page = ({"type": "FeatureCollection", "features": [{"type": "Feature"}]}
                if params["resultOffset"] == 0 else {"error": {"code": 500}})
        return Mock(json=lambda: page)

    monkeypatch.setattr(download.requests, "get", get_page)
    monkeypatch.setattr(download.time, "sleep", lambda seconds: None)
    with pytest.raises(ValueError, match="feature collection"):
        download.download_in_pages("https://example.invalid", destination, 1)
    assert destination.read_text() == "previous export"
