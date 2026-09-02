from fastapi.testclient import TestClient


def test_web_app_and_assets_are_served(api_client: TestClient) -> None:
    page = api_client.get("/")
    stylesheet = api_client.get("/assets/app.css")
    script = api_client.get("/assets/app.js")

    assert page.status_code == 200
    assert "Calendar" in page.text
    assert "Tasks" in page.text
    assert "Household" in page.text
    assert "Invite member" in page.text
    assert "Create a task" in page.text
    assert "Planned with" in page.text
    assert "Sign in to Dishpute" in page.text
    assert "auth-error" in page.text
    assert "Use at least 10 characters" in page.text
    assert "Set up your household" in page.text
    assert "Create family invite" in page.text
    assert "/assets/app.js?v=" in page.text
    assert stylesheet.status_code == 200
    assert "calendar-grid" in stylesheet.text
    assert script.status_code == 200
    assert "calendar-items" in script.text
    assert "work-items" in script.text
    assert 'localStorage.getItem("dishpute.accessToken")' in script.text
    assert 'api("/households/join"' in script.text
    assert "do not match a Dishpute account" in script.text
    assert "formatApiError" in script.text
    assert "renderHousehold" in script.text
    assert "createTask" in script.text
