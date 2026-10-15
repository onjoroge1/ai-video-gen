"""A cited page and a searched page match with or without "www." (hippo remake, 2026-10-15)."""
from longform_research import _canonical_url


def test_www_and_bare_host_are_the_same_page():
    cited = "https://www.cbsnews.com/amp/news/colombia-cocaine-hippos-pablo-escobars-invasive-species"
    searched = "https://cbsnews.com/amp/news/colombia-cocaine-hippos-pablo-escobars-invasive-species/"
    assert _canonical_url(cited) == _canonical_url(searched)


def test_other_hosts_and_paths_stay_distinct():
    assert _canonical_url("https://www.cbsnews.com/a") != _canonical_url("https://news.cbsnews.com/a")
    assert _canonical_url("https://wwwx.example.com/a") == "https://wwwx.example.com/a"
    assert _canonical_url("https://www.cbsnews.com/a") != _canonical_url("https://www.cbsnews.com/b")
