"""Security headers on every response (docs/SECURITY_F9.md).

  X-Content-Type-Options: nosniff          the browser must not guess a type different from the one sent
  X-Frame-Options: DENY                    the pages cannot be shown inside another site (clickjacking)
  Referrer-Policy: no-referrer             no address is leaked to other sites
  Cache-Control: no-store                  sessions, keys and results are never kept by a browser or a proxy
  Content-Security-Policy                  an API answer is data: no script, no frame, nothing to load
  Strict-Transport-Security                only on requests that arrived over HTTPS

The interactive documentation (/api/docs/) is a web page with its own scripts: it gets the first three, not the last two.
"""
from flask import request


def init_security(app):
    @app.after_request
    def add_headers(response):
        response.headers.setdefault('X-Content-Type-Options', 'nosniff')
        response.headers.setdefault('X-Frame-Options', 'DENY')
        response.headers.setdefault('Referrer-Policy', 'no-referrer')

        if not request.path.startswith('/api/docs'):
            response.headers.setdefault('Cache-Control', 'no-store')
            response.headers.setdefault('Content-Security-Policy', "default-src 'none'; frame-ancestors 'none'")

        seconds = app.config.get('HSTS_SECONDS', 0)
        if seconds and request.is_secure:
            response.headers.setdefault('Strict-Transport-Security', f'max-age={seconds}; includeSubDomains')
        return response
