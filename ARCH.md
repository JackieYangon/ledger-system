# Architecture

## Overview
The system is a server-rendered web application built on FastAPI with Jinja2 templates and TailwindCSS (CDN). SQLite persists data locally. The app is designed for desktop-first usage with multi-user roles.

## Components
- **FastAPI app**: Request routing, form handling, and session management.
- **Jinja2 templates**: Server-rendered pages for dashboards, listings, and admin screens.
- **SQLAlchemy ORM**: Defines data models and handles database queries.
- **SQLite**: Local single-file database stored at `data/app.db`.
- **Session Middleware**: Cookie-based login session using a server-side secret key.

## Request Flow
1. Client requests a page.
2. Session middleware resolves `user_id` from cookies.
3. Route handler loads data via SQLAlchemy and enforces role-based access.
4. Jinja2 renders HTML with Tailwind styling.

## Data Model Mapping
- `organizations`: Owns all other entities.
- `users`: Belongs to organization, has role and credentials.
- `accounts`: Money sources per organization.
- `categories`: Income or expense categories per organization.
- `transactions`: Core ledger entries.
- `budgets`: Optional category budgets with date ranges.
- `audit_logs`: Reserved for future operational auditing.

## Role Enforcement
- **admin**: Full access, manage users, accounts, categories.
- **user**: Can create transactions, budgets, view reports, limited to own transactions.
- **readonly**: View-only access to all reports and transactions.

## Runtime
- App entrypoint: `app.main:app`
- Database init: `Base.metadata.create_all` at startup
- Static assets: mounted at `/static`

## Deployment
- Dockerfile builds a slim image using Python.
- docker-compose mounts `data/` for persistent SQLite storage.
