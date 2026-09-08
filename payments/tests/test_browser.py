import pytest
from django.contrib.auth import get_user_model
from django.test import Client


@pytest.mark.django_db
def test_browser_login_and_csrf():
    get_user_model().objects.create_user(username='browser', password='browser-test-password')
    browser = Client(enforce_csrf_checks=True)
    login = browser.get('/api-auth/login/?next=/api/')
    assert login.status_code == 200
    csrf = browser.cookies['csrftoken'].value
    response = browser.post('/api-auth/login/', {'username': 'browser', 'password': 'browser-test-password', 'csrfmiddlewaretoken': csrf, 'next': '/api/'})
    assert response.status_code == 302
    assert response.url == '/api/'
    assert browser.get('/api/').status_code == 200
    assert browser.get('/api/bills/').status_code == 200
    payload = {'customer_number': 'BROWSER', 'name': 'Browser', 'email': 'browser@example.com'}
    assert browser.post('/api/customers/', payload).status_code == 403
    assert browser.post('/api/customers/', payload, HTTP_X_CSRFTOKEN=browser.cookies['csrftoken'].value).status_code == 201


@pytest.mark.django_db
def test_browser_logout_removes_access():
    user = get_user_model().objects.create_user(username='logout', password='browser-test-password')
    browser = Client()
    browser.force_login(user)
    assert browser.get('/api/').status_code == 200
    assert browser.post('/api-auth/logout/').status_code == 302
    assert browser.get('/api/').status_code == 401
