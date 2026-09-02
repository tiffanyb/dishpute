from fastapi.testclient import TestClient


def test_web_app_and_assets_are_served(api_client: TestClient) -> None:
    page = api_client.get("/")
    stylesheet = api_client.get("/assets/app.css")
    script = api_client.get("/assets/app.js")

    assert page.status_code == 200
    assert "Calendar" in page.text
    assert "Tasks" in page.text
    assert stylesheet.status_code == 200
    assert "calendar-grid" in stylesheet.text
    assert script.status_code == 200
    assert "calendar-items" in script.text
    assert "work-items" in script.text
