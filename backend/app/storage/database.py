"""Select PostgreSQL for deployed apps; preserve isolated SQLite local tests."""
from app.config.settings import settings
from app.storage.postgres import Database as PostgresDatabase
from app.storage.sqlite import Database as SQLiteDatabase

# SQLite is a legacy local-test convenience; deployed services must set DATABASE_URL.
Database = PostgresDatabase if settings.database_url else SQLiteDatabase
db = Database()
