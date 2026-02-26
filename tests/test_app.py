from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.main import app
from app.db import Base, get_db
from app.models import Category, Account, User


@pytest.fixture()
def client(tmp_path):
    db_path = tmp_path / "test.db"
    engine = create_engine(
        f"sqlite:///{db_path}", connect_args={"check_same_thread": False}
    )
    TestingSessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    Base.metadata.create_all(bind=engine)

    def override_get_db():
        db = TestingSessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db

    with TestClient(app) as test_client:
        test_client.session_local = TestingSessionLocal
        yield test_client

    app.dependency_overrides.clear()


def register_admin(client, email="admin@example.com", password="secret"):
    resp = client.post(
        "/register",
        data={
            "org_name": "Acme Org",
            "name": "Admin",
            "email": email,
            "password": password,
        },
        follow_redirects=True,
    )
    assert resp.status_code == 200
    return email, password


def login(client, email, password):
    resp = client.post(
        "/login", data={"email": email, "password": password}, follow_redirects=True
    )
    assert resp.status_code == 200


def logout(client):
    client.get("/logout", follow_redirects=True)


def create_user(client, name, email, role, password="secret"):
    resp = client.post(
        "/admin/users",
        data={
            "name": name,
            "email": email,
            "role": role,
            "password": password,
        },
        follow_redirects=True,
    )
    assert resp.status_code == 200


def get_default_ids(client):
    with client.session_local() as db:
        category = db.query(Category).filter(Category.type == "expense").first()
        account = db.query(Account).first()
    return category.id, account.id


def test_permissions_and_visibility(client):
    admin_email, admin_password = register_admin(client)
    create_user(client, "User One", "user1@example.com", "user")
    create_user(client, "Read Only", "readonly@example.com", "readonly")

    category_id, account_id = get_default_ids(client)

    # Admin creates a transaction
    resp = client.post(
        "/transactions/new",
        data={
            "amount": "10.00",
            "type": "expense",
            "occurred_at": date.today().isoformat(),
            "category_id": category_id,
            "account_id": account_id,
            "note": "admin-note",
            "tags": "team",
        },
        follow_redirects=True,
    )
    assert resp.status_code == 200

    # User can only see their own transactions
    logout(client)
    login(client, "user1@example.com", "secret")
    resp = client.post(
        "/transactions/new",
        data={
            "amount": "5.00",
            "type": "expense",
            "occurred_at": date.today().isoformat(),
            "category_id": category_id,
            "account_id": account_id,
            "note": "user-note",
            "tags": "personal",
        },
        follow_redirects=True,
    )
    assert resp.status_code == 200
    resp = client.get("/transactions")
    assert "user-note" in resp.text
    assert "admin-note" not in resp.text

    # Normal user cannot access admin pages
    resp = client.get("/accounts")
    assert resp.status_code == 403

    # Read-only cannot create transactions
    logout(client)
    login(client, "readonly@example.com", "secret")
    resp = client.post(
        "/transactions/new",
        data={
            "amount": "3.00",
            "type": "expense",
            "occurred_at": date.today().isoformat(),
            "category_id": category_id,
            "account_id": account_id,
            "note": "readonly-try",
            "tags": "",
        },
    )
    assert resp.status_code == 403


def test_transaction_creation_and_list(client):
    register_admin(client)
    category_id, account_id = get_default_ids(client)

    resp = client.post(
        "/transactions/new",
        data={
            "amount": "1200.50",
            "type": "income",
            "occurred_at": date.today().isoformat(),
            "category_id": category_id,
            "account_id": account_id,
            "note": "salary",
            "tags": "income",
        },
        follow_redirects=True,
    )
    assert resp.status_code == 200

    resp = client.get("/transactions")
    assert "salary" in resp.text
    assert "1200.50" in resp.text


def test_filters(client):
    register_admin(client)
    category_id, account_id = get_default_ids(client)

    # Add a second account and category for filtering
    client.post(
        "/accounts",
        data={"name": "Bank", "type": "bank", "currency": "CNY"},
        follow_redirects=True,
    )
    client.post(
        "/categories",
        data={"name": "Travel", "type": "expense"},
        follow_redirects=True,
    )

    with client.session_local() as db:
        bank_account = db.query(Account).filter(Account.name == "Bank").first()
        travel_category = db.query(Category).filter(Category.name == "Travel").first()

    today = date.today()
    yesterday = today - timedelta(days=1)

    client.post(
        "/transactions/new",
        data={
            "amount": "10.00",
            "type": "expense",
            "occurred_at": today.isoformat(),
            "category_id": category_id,
            "account_id": account_id,
            "note": "coffee",
            "tags": "morning",
        },
        follow_redirects=True,
    )
    client.post(
        "/transactions/new",
        data={
            "amount": "50.00",
            "type": "expense",
            "occurred_at": yesterday.isoformat(),
            "category_id": travel_category.id,
            "account_id": bank_account.id,
            "note": "flight",
            "tags": "trip",
        },
        follow_redirects=True,
    )
    client.post(
        "/transactions/new",
        data={
            "amount": "1000.00",
            "type": "income",
            "occurred_at": today.isoformat(),
            "category_id": category_id,
            "account_id": account_id,
            "note": "salary",
            "tags": "income",
        },
        follow_redirects=True,
    )

    resp = client.get(
        f"/transactions?start_date={today.isoformat()}&end_date={today.isoformat()}"
    )
    assert "coffee" in resp.text
    assert "salary" in resp.text
    assert "flight" not in resp.text

    resp = client.get(f"/transactions?category_id={travel_category.id}")
    assert "flight" in resp.text
    assert "coffee" not in resp.text

    resp = client.get(f"/transactions?account_id={bank_account.id}")
    assert "flight" in resp.text
    assert "coffee" not in resp.text

    resp = client.get("/transactions?min_amount=20&max_amount=60")
    assert "flight" in resp.text
    assert "coffee" not in resp.text

    resp = client.get("/transactions?q=coffee")
    assert "coffee" in resp.text
    assert "flight" not in resp.text


def test_reports(client):
    register_admin(client)
    category_id, account_id = get_default_ids(client)

    today = date.today()
    if today.month > 1:
        extra_date = date(today.year, today.month - 1, 1)
    else:
        extra_date = date(today.year, today.month, 1)

    client.post(
        "/transactions/new",
        data={
            "amount": "500.00",
            "type": "income",
            "occurred_at": today.isoformat(),
            "category_id": category_id,
            "account_id": account_id,
            "note": "report-income",
            "tags": "",
        },
        follow_redirects=True,
    )
    client.post(
        "/transactions/new",
        data={
            "amount": "120.00",
            "type": "expense",
            "occurred_at": today.isoformat(),
            "category_id": category_id,
            "account_id": account_id,
            "note": "report-expense",
            "tags": "",
        },
        follow_redirects=True,
    )
    client.post(
        "/transactions/new",
        data={
            "amount": "80.00",
            "type": "expense",
            "occurred_at": extra_date.isoformat(),
            "category_id": category_id,
            "account_id": account_id,
            "note": "report-extra",
            "tags": "",
        },
        follow_redirects=True,
    )

    if extra_date.month == today.month:
        month_expense = 200.00
    else:
        month_expense = 120.00

    year_expense = 200.00

    resp = client.get("/reports")
    assert "500.00" in resp.text
    assert f"{month_expense:.2f}" in resp.text
    assert f"{year_expense:.2f}" in resp.text


def test_budgets_tracking(client):
    register_admin(client)
    category_id, account_id = get_default_ids(client)

    today = date.today()
    start_date = date(today.year, today.month, 1)
    end_date = date(today.year, today.month, min(28, today.day))

    client.post(
        "/budgets",
        data={
            "name": "Food Budget",
            "period": "monthly",
            "amount": "300.00",
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat(),
            "category_id": category_id,
        },
        follow_redirects=True,
    )

    client.post(
        "/transactions/new",
        data={
            "amount": "120.00",
            "type": "expense",
            "occurred_at": today.isoformat(),
            "category_id": category_id,
            "account_id": account_id,
            "note": "budget-spend",
            "tags": "",
        },
        follow_redirects=True,
    )

    resp = client.get("/budgets")
    assert "Food Budget" in resp.text
    assert "120.00" in resp.text
    assert "300.00" in resp.text


def test_export_csv(client):
    register_admin(client)
    category_id, account_id = get_default_ids(client)

    client.post(
        "/transactions/new",
        data={
            "amount": "45.00",
            "type": "expense",
            "occurred_at": date.today().isoformat(),
            "category_id": category_id,
            "account_id": account_id,
            "note": "export-me",
            "tags": "csv",
        },
        follow_redirects=True,
    )

    resp = client.get(f"/export?category_id={category_id}")
    assert resp.status_code == 200
    assert resp.headers.get("content-type", "").startswith("text/csv")
    assert "export-me" in resp.text


def test_desktop_flow_pages(client):
    register_admin(client)
    resp = client.get("/transactions")
    assert resp.status_code == 200
    assert "New Transaction" in resp.text

    resp = client.get("/transactions/new")
    assert resp.status_code == 200
    assert "Amount" in resp.text
    assert "Date" in resp.text
