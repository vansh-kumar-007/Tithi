"""
WSGI entrypoint for production servers (e.g., Gunicorn on Render).
"""
from app import create_app

app = create_app()
