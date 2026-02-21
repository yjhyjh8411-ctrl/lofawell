from firebase_functions import https_fn
from app import app
import sys

@https_fn.on_request(max_instances=10)
def lofawell(req: https_fn.Request) -> https_fn.Response:
    try:
        print(f"Incoming request: {req.method} {req.path}", file=sys.stderr)
        
        # Ensure path_info is correct (Flask relies on it)
        if not req.environ.get('PATH_INFO'):
            req.environ['PATH_INFO'] = req.path

        with app.request_context(req.environ):
            return app.full_dispatch_request()
    except Exception as e:
        print(f"Error handling request: {e}", file=sys.stderr)
        return https_fn.Response("Internal Server Error", status=500)