import http.server
import socketserver
import os
import argparse
from urllib.parse import urlparse

# Define explicitly allowed prefixes for security
# Only these paths will be served. Everything else returns 403 Forbidden.
ALLOWED_PREFIXES = (
    "/pages/",
    "/assets/",
    "/index.html",
    "/favicon.ico",
    "/Logo/",
    "/robots.txt",
)

class SecureFrontendHandler(http.server.SimpleHTTPRequestHandler):
    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        
        # Security check: Does path try to leak something outside allowed dirs?
        # For instance: /.env, /backend, /START.bat, etc.
        if not path.startswith(ALLOWED_PREFIXES) and path != "/":
            self.send_error(403, "Forbidden")
            return
            
        # Do not allow hidden files ever, even inside allowed folders
        if "/." in path:
            self.send_error(403, "Forbidden")
            return
            
        super().do_GET()

    def end_headers(self):
        self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
        self.send_header("Pragma", "no-cache")
        self.send_header("Expires", "0")
        super().end_headers()

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument('port', type=int, nargs='?', default=3000)
    parser.add_argument('--bind', '-b', default='127.0.0.1', metavar='ADDRESS')
    args = parser.parse_args()

    # Move to the root directory where the script is located
    os.chdir(os.path.dirname(os.path.abspath(__file__)))

    Handler = SecureFrontendHandler
    with socketserver.TCPServer((args.bind, args.port), Handler) as httpd:
        print(f"Securely serving frontend at http://{args.bind}:{args.port}")
        print(f"Only serving explicitly allowed directories: {ALLOWED_PREFIXES}")
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            pass
