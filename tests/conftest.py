import os

os.environ.setdefault('PROXSTAR_TESTING', 'true')
os.environ.setdefault('PROXSTAR_SQLALCHEMY_DATABASE_URI', 'sqlite://')
os.environ.setdefault('PROXSTAR_REDIS_HOST', 'localhost')
os.environ.setdefault('PROXSTAR_REDIS_PORT', '6379')
