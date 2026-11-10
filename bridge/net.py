"""Local service traffic must not go through a system HTTP proxy."""

import urllib.request
from urllib.parse import urlsplit
import requests


def local(url):
    return urlsplit(url).hostname in ("127.0.0.1", "localhost", "::1")


def request(method, url, **kwargs):
    if local(url):
        kwargs["proxies"] = {"http": "", "https": "", "all": ""}
    return requests.request(method, url, **kwargs)


def urlopen(request, timeout=10):
    url = request if isinstance(request, str) else request.full_url
    if local(url):
        return urllib.request.build_opener(urllib.request.ProxyHandler({})).open(
            request, timeout=timeout
        )
    return urllib.request.urlopen(request, timeout=timeout)
