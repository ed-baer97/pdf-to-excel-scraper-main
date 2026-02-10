"""
WSGI entry point for production deployment.

This module creates the Flask application for WSGI servers
like Gunicorn, uWSGI, or Waitress.

Usage with Gunicorn:
    gunicorn -c gunicorn_config.py wsgi:app

Usage with uWSGI:
    uwsgi --http :5000 --wsgi-file wsgi.py --callable app

Usage with Waitress:
    waitress-serve --port=5000 wsgi:app
"""
from dotenv import load_dotenv

# Load environment variables before creating app
load_dotenv()

from webapp import create_app

# Create Flask application
app = create_app()

if __name__ == "__main__":
    # Direct run (for testing only, use run_production.py in production)
    app.run(host="0.0.0.0", port=5000)
