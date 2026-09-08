"""Verify browser-style cookie login and served CSS against the running app."""
from http.cookiejar import CookieJar
from urllib.parse import urlencode
from urllib.request import build_opener, HTTPCookieProcessor, Request

base = 'http://localhost:8000'
cookies = CookieJar()
browser = build_opener(HTTPCookieProcessor(cookies))
with browser.open(base + '/api-auth/login/?next=/api/', timeout=10) as response:
    assert response.status == 200
    assert b'csrfmiddlewaretoken' in response.read()
csrf = next(cookie.value for cookie in cookies if cookie.name == 'csrftoken')
form = urlencode({'username': 'demo', 'password': 'demo12345', 'csrfmiddlewaretoken': csrf, 'next': '/api/'}).encode()
with browser.open(Request(base + '/api-auth/login/', data=form), timeout=10) as response:
    assert response.status == 200
    assert response.url == base + '/api/'
with browser.open(base + '/api/bills/', timeout=10) as response:
    assert response.status == 200
with browser.open(base + '/static/rest_framework/css/bootstrap.min.css', timeout=10) as response:
    assert response.status == 200
    assert 'text/css' in response.headers['Content-Type']
    assert len(response.read()) > 1000
print('PASS: browser cookie login, authenticated API access, and CSS served over HTTP')
