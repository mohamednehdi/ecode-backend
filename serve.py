"""Production server (replaces `python run.py`, which starts Flask's development server).

    python serve.py                      # Windows / any OS (waitress)
    gunicorn -w 4 --threads 8 -k gthread -b 0.0.0.0:5000 run:app   # Linux alternative (several processes)

Settings (environment / .env):
    HOST=0.0.0.0         PORT=5000
    WAITRESS_THREADS=8   number of requests processed at the same time. The decoding libraries release
                         Python's GIL, so threads run in parallel: use about the number of CPU cores.
"""
import os

from waitress import serve

from app import create_app

app = create_app()

if __name__ == '__main__':
    host = os.environ.get('HOST', '0.0.0.0')
    port = int(os.environ.get('PORT', 5000))
    threads = int(os.environ.get('WAITRESS_THREADS', os.cpu_count() or 4))
    print(f'Serving on http://{host}:{port} with {threads} worker threads')
    # backlog: connections queued while all threads are busy; the upload limit is set by MAX_UPLOAD_MB
    serve(app, host=host, port=port, threads=threads, backlog=2048, connection_limit=2000,
          max_request_body_size=app.config['MAX_CONTENT_LENGTH'])
