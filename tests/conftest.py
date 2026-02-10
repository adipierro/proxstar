import os
import sys
from pathlib import Path

os.environ.setdefault('PROXSTAR_TESTING', 'true')
os.environ.setdefault('PROXSTAR_SQLALCHEMY_DATABASE_URI', 'sqlite://')
os.environ.setdefault('PROXSTAR_REDIS_HOST', 'localhost')
os.environ.setdefault('PROXSTAR_REDIS_PORT', '6379')

repo_root = Path(__file__).resolve().parents[1]
if str(repo_root) not in sys.path:
    sys.path.insert(0, str(repo_root))
