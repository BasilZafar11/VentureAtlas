from pathlib import Path
import tempfile
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect
from sqlalchemy.schema import CreateTable
from sqlalchemy.dialects import postgresql
from app.models.database import Base


def test_postgres_schema_uses_uuid_jsonb_and_foreign_keys():
    sql = '\n'.join(str(CreateTable(t).compile(dialect=postgresql.dialect())) for t in Base.metadata.sorted_tables)
    assert 'id UUID' in sql and 'JSONB' in sql and 'ON DELETE CASCADE' in sql


def test_migration_roundtrip(monkeypatch):
    import app.db.session as session
    db=create_engine('sqlite:///' + str(Path(tempfile.mkdtemp())/'migration.db'))
    monkeypatch.setattr(session,'engine',db)
    config=Config('alembic.ini')
    command.upgrade(config,'head')
    assert set(inspect(db).get_table_names()) == {'alembic_version','analyses','competitors','signals','evidence', 'novelty_reports','novelty_usage','novelty_daily_budget','novelty_workspaces', 'venture_accounts','venture_sessions','venture_teams','research_states','groq_daily_budget','serpapi_user_budget'}
    command.downgrade(config,'base')
    assert inspect(db).get_table_names()==['alembic_version']
