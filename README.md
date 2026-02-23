# GTT SmartBot — EXIM Trade Intelligence Backend

An enterprise-grade, production-ready AI chatbot backend designed for the Import-Export industry. This platform automates customer interaction, qualifies leads, and streamlines sales through intelligent conversation and secure data management.

## 🚀 Core Features

- **🔐 Enterprise Authentication:** Robust JWT-based auth with separate Access and Refresh tokens (1-hour expiry for access, 30-day for refresh).
- **🧠 AI Intent Engine:** Dynamic intent detection for "Sales", "Support", and "Inquiry" with automated Call-to-Action (CTA) triggers.
- **📈 Lead Management:** Automated lead capture, qualification, and cleaning (`cleanup_leads.py`).
- **⚙️ Admin Controls:** Administrative APIs for managing intents, greetings, and system configuration without code changes.
- **🏢 Multi-Layered Architecture:** Scalable design separating API logic, business services, and database models.
- **🔌 Enterprise Connectivity:** Ready for SQL Server integration using PyODBC and SQLAlchemy.

## 🛠️ Technology Stack

- **Framework:** [FastAPI](https://fastapi.tiangolo.com/) (Python 3.10+)
- **Database:** [SQLAlchemy 2.0](https://www.sqlalchemy.org/) with SQL Server integration.
- **Migrations:** [Alembic](https://alembic.sqlalchemy.org/) for version-controlled schema updates.
- **Validation:** [Pydantic v2](https://docs.pydantic.dev/) for strict data schema enforcement.
- **Security:** JWT (JSON Web Tokens) with `python-jose` and `passlib`.
- **Async Processing:** `httpx` for non-blocking external API communications.

## 📁 Project Structure

```text
Backend_bot/
├── app/
│   ├── api/          # Route handlers (auth, leads, chatbot, admin)
│   ├── core/         # Security, Config (pydantic-settings)
│   ├── db/           # Database session & base models
│   ├── models/       # SQLAlchemy ORM models
│   ├── schemas/      # Pydantic validation schemas
│   ├── services/     # Business logic & AI integration
│   └── main.py       # Application entry point & Lifespan management
├── alembic/          # Database migration history
├── .env              # Environment variables (secrets)
├── requirements.txt  # Project dependencies
└── seed_intents.py   # Initial database seeding script
```

## ⚙️ Installation & Setup

### 1. Prerequisites
- Python 3.10 or higher
- SQL Server (or configured DATABASE_URL)

### 2. Environment Setup
Create a `.env` file in the root directory:
```env
APP_NAME="GTT SmartBot"
DATABASE_URL="mssql+pyodbc://..."
SECRET_KEY="your-production-secret"
JWT_SECRET_KEY="your-jwt-secret"
FRONTEND_ORIGIN="http://localhost:3000"
```

### 3. Install Dependencies
```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

### 4. Database Migrations
```bash
alembic upgrade head
python seed_intents.py  # Seed initial chatbot intents
```

### 5. Run the Server
```bash
uvicorn app.main:app --reload
```

## 📌 Recent Milestones
1. **Refactor v5.0:** Transitioned from a generic structure to a robust layered architecture.
2. **Sales/Demo Engine:** Implemented high-intent detection that triggers "Request Demo" CTA cards.
3. **Enterprise Auth:** Added secure refresh token rotation and role-based access logic.
4. **Admin UI Support:** Developed endpoints to allow dynamic updates to greeting messages.

---
*Developed for EXIM Trade Intelligence Platform.*
