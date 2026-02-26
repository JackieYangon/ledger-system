import csv
import os
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from io import StringIO

from fastapi import FastAPI, Request, Depends, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware
from sqlalchemy import func, and_
from sqlalchemy.orm import Session

from .db import Base, engine, get_db
from .models import (
    Organization,
    User,
    Account,
    Category,
    Transaction,
    Budget,
)
from .auth import hash_password, verify_password

app = FastAPI()
app.add_middleware(
    SessionMiddleware,
    secret_key=os.getenv("SECRET_KEY", "dev-secret-key"),
    session_cookie="ledger_session",
)

Base.metadata.create_all(bind=engine)

app.mount("/static", StaticFiles(directory="app/static"), name="static")
templates = Jinja2Templates(directory="app/templates")


ROLE_ADMIN = "admin"
ROLE_USER = "user"
ROLE_READONLY = "readonly"


def get_current_user(request: Request, db: Session) -> User | None:
    user_id = request.session.get("user_id")
    if not user_id:
        return None
    return db.get(User, user_id)


def require_role(user: User, allowed: set[str]):
    if user.role not in allowed:
        raise HTTPException(status_code=403, detail="Access denied")


def parse_amount_to_cents(amount_str: str) -> int:
    try:
        value = Decimal(amount_str)
    except (InvalidOperation, TypeError):
        raise ValueError("Invalid amount")
    return int((value * 100).quantize(Decimal("1")))


def cents_to_display(cents: int) -> str:
    return f"{cents / 100:.2f}"


def base_context(request: Request, user: User | None, **kwargs):
    ctx = {"request": request, "user": user}
    ctx.update(kwargs)
    return ctx


def seed_defaults(db: Session, org: Organization):
    if db.query(Category).filter(Category.org_id == org.id).count() == 0:
        defaults = [
            ("Salary", "income"),
            ("Bonus", "income"),
            ("Food", "expense"),
            ("Rent", "expense"),
            ("Transport", "expense"),
        ]
        for name, ctype in defaults:
            db.add(Category(org_id=org.id, name=name, type=ctype))
    if db.query(Account).filter(Account.org_id == org.id).count() == 0:
        db.add(Account(org_id=org.id, name="Cash", type="cash", currency="CNY"))


@app.get("/", response_class=HTMLResponse)
def dashboard(request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse("/login", status_code=303)

    today = date.today()
    month_start = date(today.year, today.month, 1)

    tx_query = db.query(Transaction).filter(Transaction.org_id == user.org_id)
    if user.role == ROLE_USER:
        tx_query = tx_query.filter(Transaction.user_id == user.id)

    month_query = tx_query.filter(Transaction.occurred_at >= month_start)

    income = (
        month_query.filter(Transaction.type == "income")
        .with_entities(func.coalesce(func.sum(Transaction.amount_cents), 0))
        .scalar()
    )
    expense = (
        month_query.filter(Transaction.type == "expense")
        .with_entities(func.coalesce(func.sum(Transaction.amount_cents), 0))
        .scalar()
    )

    budgets = db.query(Budget).filter(Budget.org_id == user.org_id).all()
    budget_summaries = []
    for budget in budgets:
        budget_query = db.query(Transaction).filter(
            Transaction.org_id == user.org_id,
            Transaction.type == "expense",
            Transaction.occurred_at >= budget.start_date,
            Transaction.occurred_at <= budget.end_date,
        )
        if budget.category_id:
            budget_query = budget_query.filter(Transaction.category_id == budget.category_id)
        spent = (
            budget_query.with_entities(func.coalesce(func.sum(Transaction.amount_cents), 0))
            .scalar()
        )
        budget_summaries.append(
            {
                "budget": budget,
                "spent": spent,
                "remaining": budget.amount_cents - spent,
            }
        )

    return templates.TemplateResponse(
        "dashboard.html",
        base_context(
            request,
            user,
            income=cents_to_display(income),
            expense=cents_to_display(expense),
            balance=cents_to_display(income - expense),
            budget_summaries=budget_summaries,
        ),
    )


@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if user:
        return RedirectResponse("/", status_code=303)
    return templates.TemplateResponse("login.html", base_context(request, None))


@app.post("/login")
def login(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
    db: Session = Depends(get_db),
):
    user = db.query(User).filter(User.email == email).first()
    if not user or not verify_password(password, user.password_hash):
        return templates.TemplateResponse(
            "login.html",
            base_context(request, None, error="Invalid credentials"),
            status_code=400,
        )
    request.session["user_id"] = user.id
    return RedirectResponse("/", status_code=303)


@app.get("/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/login", status_code=303)


@app.get("/register", response_class=HTMLResponse)
def register_page(request: Request, db: Session = Depends(get_db)):
    user_count = db.query(User).count()
    if user_count > 0:
        return templates.TemplateResponse(
            "message.html",
            base_context(
                request,
                None,
                message="Registration is closed. Ask an admin to create your account.",
            ),
            status_code=403,
        )
    return templates.TemplateResponse("register.html", base_context(request, None))


@app.post("/register")
def register(
    request: Request,
    org_name: str = Form(...),
    name: str = Form(...),
    email: str = Form(...),
    password: str = Form(...),
    db: Session = Depends(get_db),
):
    if db.query(User).count() > 0:
        return RedirectResponse("/login", status_code=303)

    org = Organization(name=org_name)
    db.add(org)
    db.flush()

    admin = User(
        org_id=org.id,
        name=name,
        email=email,
        password_hash=hash_password(password),
        role=ROLE_ADMIN,
    )
    db.add(admin)
    seed_defaults(db, org)
    db.commit()

    request.session["user_id"] = admin.id
    return RedirectResponse("/", status_code=303)


@app.get("/transactions", response_class=HTMLResponse)
def transactions_list(request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse("/login", status_code=303)

    params = request.query_params
    start_date_raw = params.get("start_date")
    end_date_raw = params.get("end_date")
    category_id = params.get("category_id")
    account_id = params.get("account_id")
    min_amount = params.get("min_amount")
    max_amount = params.get("max_amount")
    keyword = params.get("q")

    query = db.query(Transaction).filter(Transaction.org_id == user.org_id)
    if user.role == ROLE_USER:
        query = query.filter(Transaction.user_id == user.id)

    filters = []
    start_date = None
    end_date = None
    if start_date_raw:
        try:
            start_date = datetime.strptime(start_date_raw, "%Y-%m-%d").date()
        except ValueError:
            start_date = None
    if end_date_raw:
        try:
            end_date = datetime.strptime(end_date_raw, "%Y-%m-%d").date()
        except ValueError:
            end_date = None
    if start_date:
        filters.append(Transaction.occurred_at >= start_date)
    if end_date:
        filters.append(Transaction.occurred_at <= end_date)
    if category_id:
        filters.append(Transaction.category_id == int(category_id))
    if account_id:
        filters.append(Transaction.account_id == int(account_id))
    if min_amount:
        try:
            filters.append(Transaction.amount_cents >= parse_amount_to_cents(min_amount))
        except ValueError:
            pass
    if max_amount:
        try:
            filters.append(Transaction.amount_cents <= parse_amount_to_cents(max_amount))
        except ValueError:
            pass
    if keyword:
        filters.append(
            func.lower(func.coalesce(Transaction.note, "")).like(f"%{keyword.lower()}%")
            | func.lower(func.coalesce(Transaction.tags, "")).like(
                f"%{keyword.lower()}%"
            )
        )

    if filters:
        query = query.filter(and_(*filters))

    transactions = query.order_by(Transaction.occurred_at.desc()).limit(500).all()

    income = (
        query.filter(Transaction.type == "income")
        .with_entities(func.coalesce(func.sum(Transaction.amount_cents), 0))
        .scalar()
    )
    expense = (
        query.filter(Transaction.type == "expense")
        .with_entities(func.coalesce(func.sum(Transaction.amount_cents), 0))
        .scalar()
    )

    categories = (
        db.query(Category).filter(Category.org_id == user.org_id).order_by(Category.name).all()
    )
    accounts = (
        db.query(Account).filter(Account.org_id == user.org_id).order_by(Account.name).all()
    )

    return templates.TemplateResponse(
        "transactions_list.html",
        base_context(
            request,
            user,
            transactions=transactions,
            categories=categories,
            accounts=accounts,
            income=cents_to_display(income),
            expense=cents_to_display(expense),
            balance=cents_to_display(income - expense),
        ),
    )


@app.get("/transactions/new", response_class=HTMLResponse)
def transaction_new_page(request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse("/login", status_code=303)
    if user.role == ROLE_READONLY:
        raise HTTPException(status_code=403, detail="Read-only")

    categories = (
        db.query(Category).filter(Category.org_id == user.org_id).order_by(Category.name).all()
    )
    accounts = (
        db.query(Account).filter(Account.org_id == user.org_id).order_by(Account.name).all()
    )
    return templates.TemplateResponse(
        "transaction_form.html",
        base_context(
            request,
            user,
            categories=categories,
            accounts=accounts,
            today=date.today().isoformat(),
        ),
    )


@app.post("/transactions/new")
def transaction_create(
    request: Request,
    amount: str = Form(...),
    type: str = Form(...),
    occurred_at: str = Form(...),
    category_id: int = Form(...),
    account_id: int = Form(...),
    note: str = Form(""),
    tags: str = Form(""),
    db: Session = Depends(get_db),
):
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse("/login", status_code=303)
    if user.role == ROLE_READONLY:
        raise HTTPException(status_code=403, detail="Read-only")

    amount_cents = parse_amount_to_cents(amount)
    tx = Transaction(
        org_id=user.org_id,
        user_id=user.id,
        account_id=account_id,
        category_id=category_id,
        amount_cents=amount_cents,
        type=type,
        occurred_at=datetime.strptime(occurred_at, "%Y-%m-%d").date(),
        note=note or None,
        tags=tags or None,
    )
    db.add(tx)
    db.commit()
    return RedirectResponse("/transactions", status_code=303)


@app.get("/accounts", response_class=HTMLResponse)
def accounts_page(request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse("/login", status_code=303)
    require_role(user, {ROLE_ADMIN})

    accounts = db.query(Account).filter(Account.org_id == user.org_id).order_by(Account.name).all()
    return templates.TemplateResponse(
        "accounts.html",
        base_context(request, user, accounts=accounts),
    )


@app.post("/accounts")
def accounts_create(
    request: Request,
    name: str = Form(...),
    type: str = Form("cash"),
    currency: str = Form("CNY"),
    db: Session = Depends(get_db),
):
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse("/login", status_code=303)
    require_role(user, {ROLE_ADMIN})

    db.add(Account(org_id=user.org_id, name=name, type=type, currency=currency))
    db.commit()
    return RedirectResponse("/accounts", status_code=303)


@app.get("/categories", response_class=HTMLResponse)
def categories_page(request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse("/login", status_code=303)
    require_role(user, {ROLE_ADMIN})

    categories = (
        db.query(Category).filter(Category.org_id == user.org_id).order_by(Category.name).all()
    )
    return templates.TemplateResponse(
        "categories.html",
        base_context(request, user, categories=categories),
    )


@app.post("/categories")
def categories_create(
    request: Request,
    name: str = Form(...),
    type: str = Form(...),
    db: Session = Depends(get_db),
):
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse("/login", status_code=303)
    require_role(user, {ROLE_ADMIN})

    db.add(Category(org_id=user.org_id, name=name, type=type))
    db.commit()
    return RedirectResponse("/categories", status_code=303)


@app.get("/budgets", response_class=HTMLResponse)
def budgets_page(request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse("/login", status_code=303)

    budgets = db.query(Budget).filter(Budget.org_id == user.org_id).order_by(Budget.id.desc()).all()
    categories = (
        db.query(Category).filter(Category.org_id == user.org_id).order_by(Category.name).all()
    )

    summaries = []
    for budget in budgets:
        tx_query = db.query(Transaction).filter(
            Transaction.org_id == user.org_id,
            Transaction.type == "expense",
            Transaction.occurred_at >= budget.start_date,
            Transaction.occurred_at <= budget.end_date,
        )
        if budget.category_id:
            tx_query = tx_query.filter(Transaction.category_id == budget.category_id)
        spent = (
            tx_query.with_entities(func.coalesce(func.sum(Transaction.amount_cents), 0))
            .scalar()
        )
        summaries.append({"budget": budget, "spent": spent})

    return templates.TemplateResponse(
        "budgets.html",
        base_context(request, user, budgets=summaries, categories=categories),
    )


@app.post("/budgets")
def budgets_create(
    request: Request,
    name: str = Form(...),
    period: str = Form(...),
    amount: str = Form(...),
    start_date: str = Form(...),
    end_date: str = Form(...),
    category_id: int | None = Form(None),
    db: Session = Depends(get_db),
):
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse("/login", status_code=303)
    if user.role == ROLE_READONLY:
        raise HTTPException(status_code=403, detail="Read-only")

    amount_cents = parse_amount_to_cents(amount)
    budget = Budget(
        org_id=user.org_id,
        name=name,
        period=period,
        category_id=category_id,
        amount_cents=amount_cents,
        start_date=datetime.strptime(start_date, "%Y-%m-%d").date(),
        end_date=datetime.strptime(end_date, "%Y-%m-%d").date(),
    )
    db.add(budget)
    db.commit()
    return RedirectResponse("/budgets", status_code=303)


@app.get("/reports", response_class=HTMLResponse)
def reports_page(request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse("/login", status_code=303)

    today = date.today()
    year_start = date(today.year, 1, 1)
    month_start = date(today.year, today.month, 1)

    base_query = db.query(Transaction).filter(Transaction.org_id == user.org_id)
    if user.role == ROLE_USER:
        base_query = base_query.filter(Transaction.user_id == user.id)

    def sum_for_range(start: date):
        income = (
            base_query.filter(Transaction.occurred_at >= start, Transaction.type == "income")
            .with_entities(func.coalesce(func.sum(Transaction.amount_cents), 0))
            .scalar()
        )
        expense = (
            base_query.filter(Transaction.occurred_at >= start, Transaction.type == "expense")
            .with_entities(func.coalesce(func.sum(Transaction.amount_cents), 0))
            .scalar()
        )
        return income, expense

    month_income, month_expense = sum_for_range(month_start)
    year_income, year_expense = sum_for_range(year_start)

    category_breakdown = (
        db.query(Category.name, func.coalesce(func.sum(Transaction.amount_cents), 0))
        .join(Transaction, Transaction.category_id == Category.id)
        .filter(
            Transaction.org_id == user.org_id,
            Transaction.type == "expense",
            Transaction.occurred_at >= month_start,
        )
        .group_by(Category.name)
        .order_by(func.sum(Transaction.amount_cents).desc())
        .all()
    )

    return templates.TemplateResponse(
        "reports.html",
        base_context(
            request,
            user,
            month_income=cents_to_display(month_income),
            month_expense=cents_to_display(month_expense),
            month_balance=cents_to_display(month_income - month_expense),
            year_income=cents_to_display(year_income),
            year_expense=cents_to_display(year_expense),
            year_balance=cents_to_display(year_income - year_expense),
            category_breakdown=category_breakdown,
        ),
    )


@app.get("/admin/users", response_class=HTMLResponse)
def users_page(request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse("/login", status_code=303)
    require_role(user, {ROLE_ADMIN})

    users = db.query(User).filter(User.org_id == user.org_id).order_by(User.name).all()
    return templates.TemplateResponse(
        "users.html",
        base_context(request, user, users=users),
    )


@app.post("/admin/users")
def users_create(
    request: Request,
    name: str = Form(...),
    email: str = Form(...),
    role: str = Form(...),
    password: str = Form(...),
    db: Session = Depends(get_db),
):
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse("/login", status_code=303)
    require_role(user, {ROLE_ADMIN})

    db.add(
        User(
            org_id=user.org_id,
            name=name,
            email=email,
            password_hash=hash_password(password),
            role=role,
        )
    )
    db.commit()
    return RedirectResponse("/admin/users", status_code=303)


@app.get("/export")
def export_csv(request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse("/login", status_code=303)

    params = request.query_params
    start_date_raw = params.get("start_date")
    end_date_raw = params.get("end_date")
    category_id = params.get("category_id")
    account_id = params.get("account_id")
    keyword = params.get("q")

    query = db.query(Transaction).filter(Transaction.org_id == user.org_id)
    if user.role == ROLE_USER:
        query = query.filter(Transaction.user_id == user.id)

    if start_date_raw:
        try:
            start_date = datetime.strptime(start_date_raw, "%Y-%m-%d").date()
            query = query.filter(Transaction.occurred_at >= start_date)
        except ValueError:
            pass
    if end_date_raw:
        try:
            end_date = datetime.strptime(end_date_raw, "%Y-%m-%d").date()
            query = query.filter(Transaction.occurred_at <= end_date)
        except ValueError:
            pass
    if category_id:
        query = query.filter(Transaction.category_id == int(category_id))
    if account_id:
        query = query.filter(Transaction.account_id == int(account_id))
    if keyword:
        query = query.filter(
            func.lower(func.coalesce(Transaction.note, "")).like(f"%{keyword.lower()}%")
            | func.lower(func.coalesce(Transaction.tags, "")).like(
                f"%{keyword.lower()}%"
            )
        )

    transactions = query.order_by(Transaction.occurred_at.desc()).all()

    buffer = StringIO()
    writer = csv.writer(buffer)
    writer.writerow(
        [
            "date",
            "type",
            "amount",
            "category",
            "account",
            "note",
            "tags",
            "user",
        ]
    )
    for tx in transactions:
        writer.writerow(
            [
                tx.occurred_at.isoformat(),
                tx.type,
                cents_to_display(tx.amount_cents),
                tx.category.name,
                tx.account.name,
                tx.note or "",
                tx.tags or "",
                tx.user.name,
            ]
        )

    buffer.seek(0)
    filename = f"ledger_export_{date.today().isoformat()}.csv"
    return StreamingResponse(
        iter([buffer.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )
