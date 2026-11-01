"""Per-IP sliding-window limiter for expensive API operations."""
from collections import deque
from time import monotonic

from starlette.responses import JSONResponse

MESSAGE = 'Too many requests from your address. Please wait a minute and try again.'


class RateLimitMiddleware:
    def __init__(self, app, limit=30, clock=monotonic):
        self.app, self.limit, self.clock = app, limit, clock
        self.requests = {}

    async def __call__(self, scope, receive, send):
        path = scope.get('path', '')
        limited = (path.startswith('/api/analyze/') or path == '/api/compare'
                   or path.startswith('/api/report/')
                   or (path == '/api/scan' and scope.get('method') == 'POST'))
        if scope['type'] == 'http' and scope.get('method') != 'OPTIONS' and self.limit > 0 and limited:
            now = self.clock()
            for ip in list(self.requests):
                queue = self.requests[ip]
                while queue and queue[0] <= now - 60:
                    queue.popleft()
                if not queue:
                    del self.requests[ip]
            headers = dict(scope.get('headers', []))
            forwarded = headers.get(b'x-forwarded-for', b'').decode('latin-1').split(',')[0].strip()
            ip = forwarded or (scope.get('client') or ('unknown',))[0]
            queue = self.requests.setdefault(ip, deque())
            if len(queue) >= self.limit:
                response = JSONResponse({'detail': MESSAGE}, status_code=429, headers={'Retry-After': '60'})
                await response(scope, receive, send)
                return
            queue.append(now)
        await self.app(scope, receive, send)
