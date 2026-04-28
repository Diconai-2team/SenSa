"""
backoffice/middleware.py — 감사 로그용 request 컨텍스트.

시그널 핸들러가 request.user / IP 를 알 수 없으므로,
미들웨어가 thread-local 에 현재 요청 정보를 저장하고
시그널이 거기서 꺼내 쓰도록 한다.
"""
import threading


_local = threading.local()


def get_current_request():
    return getattr(_local, 'request', None)


def get_current_user():
    req = get_current_request()
    if req is None:
        return None
    return getattr(req, 'user', None)


def get_current_ip():
    req = get_current_request()
    if req is None:
        return None
    # X-Forwarded-For 우선, 없으면 REMOTE_ADDR
    xff = req.META.get('HTTP_X_FORWARDED_FOR', '')
    if xff:
        return xff.split(',')[0].strip()
    return req.META.get('REMOTE_ADDR')


class AuditContextMiddleware:
    """request 시작/종료 시점에 thread-local 에 request 보관/제거.

    settings.MIDDLEWARE 에 추가:
        'backoffice.middleware.AuditContextMiddleware',
    """
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        _local.request = request
        try:
            response = self.get_response(request)
        finally:
            _local.request = None
        return response
