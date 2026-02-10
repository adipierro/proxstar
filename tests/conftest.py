import os
import sys
from pathlib import Path

os.environ.setdefault('PROXSTAR_TESTING', 'true')
os.environ.setdefault('PROXSTAR_SECRET_KEY', 'test-secret')
os.environ.setdefault('PROXSTAR_SQLALCHEMY_DATABASE_URI', 'sqlite:////tmp/proxstar_test.db')
os.environ.setdefault('PROXSTAR_REDIS_HOST', 'localhost')
os.environ.setdefault('PROXSTAR_REDIS_PORT', '6379')

repo_root = Path(__file__).resolve().parents[1]
if str(repo_root) not in sys.path:
    sys.path.insert(0, str(repo_root))

from sqlalchemy import create_engine

from proxstar.db import Base
from proxstar.models import Allowed_Users, Usage_Limit

db_path = Path('/tmp/proxstar_test.db')
if db_path.exists():
    db_path.unlink()

engine = create_engine(os.environ['PROXSTAR_SQLALCHEMY_DATABASE_URI'])
Base.metadata.create_all(engine, tables=[Usage_Limit.__table__, Allowed_Users.__table__])
