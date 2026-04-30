"""
alerts 앱 뷰

- AlarmViewSet: 알람 조회 + 읽음 처리 + 24h 통계
- alarm_list_view: 알람 상세 목록 페이지 (HTML)
"""
from datetime import timedelta
# 24h 통계 윈도우 계산용 — timezone.now() - timedelta(hours=24)
from django.contrib.auth.decorators import login_required
# 페이지 뷰 보호 데코레이터 — 비로그인 사용자를 LOGIN_URL로 리다이렉트
from django.core.paginator import Paginator
# 알람 목록 페이지네이션 — 누적 알람이 수만 건인 환경에서 필수
# 한 페이지에 너무 많은 알람이 표시되면 인지 부하 + 렌더링 부하 모두 증가
from django.shortcuts import render
# Django 템플릿 렌더링 헬퍼 — 템플릿 + 컨텍스트 → HttpResponse
from django.utils import timezone
# timezone-aware datetime 생성 — settings.USE_TZ=True 환경에서 안전한 시간 비교
from rest_framework import viewsets
# DRF의 ViewSet 클래스들 — list/retrieve를 자동 처리하는 ReadOnlyModelViewSet 사용
from rest_framework.decorators import action
# ViewSet에 커스텀 액션(stats, read, read_all) 추가용 데코레이터
# detail=True/False로 단일/컬렉션 액션 구분
from rest_framework.response import Response
# DRF용 JSON 응답 클래스 — content negotiation 지원

from .models import Alarm
from .serializers import AlarmSerializer


class AlarmViewSet(viewsets.ReadOnlyModelViewSet):
    """알람 조회 / 읽음 처리 / 통계 API"""
    # ReadOnlyModelViewSet — list/retrieve만 자동 제공, create/update/destroy는 차단
    # 알람은 services.py(상태 전이 로직)에서만 생성됨 — API로 직접 생성 못 하게 막은 의도
    # → 외부 호출자가 알람 위변조 못 함, 데이터 무결성 보장
    queryset = Alarm.objects.all().order_by("-created_at")
    # 기본 쿼리셋 — 최신순 정렬 (대시보드 알람 패널 기본 표시용)
    # get_queryset()에서 query string 기반 필터를 추가로 적용함
    serializer_class = AlarmSerializer
    # 응답 직렬화에 사용할 시리얼라이저 — geofence_name 등 포함

    def get_queryset(self):
        # 동적 필터링 — query string으로 unread/level 필터 적용
        # DRF는 list 호출 시 매번 이 메서드를 호출해 쿼리셋을 가져옴
        qs = super().get_queryset()
        # 부모의 기본 queryset(최신순 전체) 가져오기
        level = self.request.query_params.get("level", "")
        # ?level=danger 같은 query string 추출 — 없으면 빈 문자열
        if self.request.query_params.get("unread") == "true":
            qs = qs.filter(is_read=False)
            # ?unread=true — 미확인 알람만 조회 (대시보드 뱃지 카운트용)
        if level == "danger":
            qs = qs.filter(alarm_level__in=["danger", "critical"])
            # danger 필터는 critical까지 포함 — 운영자 관점에선 "위험" 한 묶음으로 보고 싶어함
        elif level in ("caution", "critical", "info"):
            qs = qs.filter(alarm_level=level)
            # 그 외 단일 레벨 필터 — 정확히 일치하는 것만
        return qs[:50]
        # ⚠️ 슬라이싱 [:50] 하드캡 — list만 보호되고 retrieve(detail)에는 적용 안 됨
        #    또한 페이지네이션 없이 50건 고정 — 클라이언트가 51번째 알람 이상 조회 불가
        #    개선안: DRF Pagination 설정으로 page_size 동적 제어

    @action(detail=False, methods=["get"])
    # detail=False — 컬렉션 레벨 액션 (특정 알람이 아닌 전체에 대한 동작)
    # URL: GET /alarm/stats/
    def stats(self, request):
        """최근 24시간 알람 통계 — GET /dashboard/api/alarm/stats/"""
        # 대시보드 상단의 통계 카드/배지 데이터 공급용
        since = timezone.now() - timedelta(hours=24)
        # 현재 시점 기준 24시간 전 컷오프
        qs = Alarm.objects.filter(created_at__gte=since)
        # 24시간 이내 알람만 필터 — 누적 데이터에서 최근 활동만 추출
        return Response({
            "danger":  qs.filter(alarm_level__in=["danger", "critical"]).count(),
            # 위험+심각 합산 — 운영자 관점 단일 카테고리
            "caution": qs.filter(alarm_level="caution").count(),
            "total":   qs.count(),
            # ⚠️ COUNT 쿼리 3번 별도 실행 — DB 부하 측면에서 비효율
            #    개선안: aggregate(Count(Case(When(...))))로 1번 쿼리에 통합 가능
        })

    @action(detail=True, methods=["patch"])
    # detail=True — 개별 객체 레벨 액션 (특정 알람에 대한 동작)
    # URL: PATCH /alarm/{id}/read/
    def read(self, request, pk=None):
        """특정 알람 읽음 처리 — PATCH /dashboard/api/alarm/{id}/read/"""
        # 운영자가 알람을 확인했음을 표시 — 미확인 카운트 감소용
        alarm = self.get_object()
        # URL의 pk로 Alarm 1건 조회 + queryset 권한 체크 자동
        # 존재하지 않으면 자동 404
        alarm.is_read = True
        alarm.save()
        # ⚠️ save() 호출 — 모든 필드 UPDATE 발생
        #    개선안: alarm.save(update_fields=['is_read']) — is_read만 UPDATE
        return Response({"status": "read", "id": alarm.id})

    @action(detail=False, methods=["patch"])
    # 컬렉션 레벨 일괄 액션 — URL: PATCH /alarm/read_all/
    def read_all(self, request):
        """전체 알람 읽음 처리 — PATCH /dashboard/api/alarm/read_all/"""
        # 사용자가 "모두 읽음" 버튼 누를 때 호출
        Alarm.objects.filter(is_read=False).update(is_read=True)
        # update() — save() 안 거치고 SQL UPDATE 직접 실행 (효율적)
        # 시그널(post_save) 미발생 — 대량 처리 시 시그널 핸들러 폭주 방지
        # 단점: auto_now 같은 필드는 갱신 안 됨 (여기선 created_at만 있어 무관)
        return Response({"status": "all read"})


@login_required(login_url="/accounts/login/")
# 비로그인 사용자는 /accounts/login/ 으로 리다이렉트 — 페이지 뷰 보호
# login_url 명시 — 프로젝트 LOGIN_URL과 별개로 강제 지정
def alarm_list_view(request):
    """알람 상세 목록 페이지 — GET /dashboard/alarms/

    [통계 카드 개선]
      이전: 전체 / 위험 / 주의 / 최근 24시간 (4개)
            → '전체 = 위험 + 주의' 라는 직관과 어긋남.
              info(회복/복귀) 알람이 큰 비중(약 50%) 인데 카드 어디에도 안 보임.
      현행: 전체 / 위험 / 주의 / 정보 / 최근 24시간 (5개)
            → 전체 = 위험 + 주의 + 정보 가 산술적으로 성립.
              필터 탭에도 '정보' 옵션 추가로 info 알람만 골라보기 가능.

    [정렬 개선]
      이전: 단순 created_at DESC.
            → 누적된 위험 알람이 시간상 과거에 묻혀 '전체' 목록에서 안 보이는 문제.
              데모/시연 시점에 새벽에 발생한 위험 알람 1300여건이 페이지 1에서 누락.
      현행: level=all 일 때만 우선순위 정렬 (critical < danger < caution < info)
            + 같은 레벨 내에서는 created_at DESC.
            → 위험/심각이 항상 상단에 보이고, 새 알람이 추가되면 같은 레벨끼리는
              여전히 최신이 위로 옴. 사용자가 본 "정상 누적" 흐름 유지.
            → 다른 필터(level=danger 등) 에서는 한 레벨만 보이므로 시간순 그대로.
            근거: ISA-18.2 §7 (알람 우선순위) — 위험 알람은 시간보다 우선 노출.
    """
    level_filter = request.GET.get("level", "all")
    # ?level=danger|caution|info|all — 기본값 'all' (전체 보기)
    qs = Alarm.objects.all()
    # 전체 알람 쿼리셋 시작점 — 아래 분기에서 필터/정렬 추가

    if level_filter == "danger":
        # 한 레벨만 보이므로 시간순이 자연스러움
        qs = qs.filter(alarm_level__in=["danger", "critical"]).order_by("-created_at")
        # danger 필터엔 critical도 포함 — get_queryset()과 동일한 정책
    elif level_filter == "caution":
        qs = qs.filter(alarm_level="caution").order_by("-created_at")
        # caution만 — 단일 레벨이라 시간순 정렬이 직관적
    elif level_filter == "info":
        qs = qs.filter(alarm_level="info").order_by("-created_at")
        # info(회복/복귀) 알람만 — 별도 탭으로 분리해 노이즈와 구분
    else:
        # level=all — 위험 우선 + 시간순 (ISA-18.2 §7)
        # critical < danger < caution < info 순으로 위에 오도록 정수 매핑.
        # 그 외 알람 레벨은 99 로 두어 가장 아래.
        from django.db.models import Case, When, IntegerField, Value
        # 함수 내부 import — 다른 분기에선 안 쓰니 모듈 로드 비용 절감
        # SQL의 CASE WHEN 표현식을 Django ORM으로 표현하기 위한 도구들
        qs = qs.annotate(
            _priority=Case(
                # 가상 필드 _priority를 매 row에 부여 — 정렬용 임시 컬럼
                When(alarm_level="critical", then=Value(0)),
                # critical은 최우선 (가장 작은 정수가 위로 옴)
                When(alarm_level="danger",   then=Value(1)),
                When(alarm_level="caution",  then=Value(2)),
                When(alarm_level="info",     then=Value(3)),
                default=Value(99),
                # 매핑되지 않은 레벨은 가장 아래 — 미래에 새 레벨 추가돼도 안전
                output_field=IntegerField(),
                # SQL 결과 타입 명시 — Django ORM이 추론 못 할 때 필요
            )
        ).order_by("_priority", "-created_at")
        # 1차 정렬: _priority(위험도) / 2차 정렬: 같은 레벨 내 최신순
        # → 새벽에 쌓인 1300여건의 위험 알람이 페이지 1 상단에 보장됨

    paginator = Paginator(qs, 20)
    # 페이지당 20건 — 20개 이상 한눈에 보면 인지 부하 큼 (UX 결정)
    # 또한 Paginator는 LIMIT/OFFSET 사용 → 큰 페이지 번호일수록 느려질 수 있음
    page_num = request.GET.get("page", 1)
    # ?page=N — 기본값 1 (첫 페이지)
    alarms = paginator.get_page(page_num)
    # get_page는 잘못된 페이지 번호도 안전하게 처리 — 음수/문자열은 1로, 초과는 마지막으로
    # vs paginator.page()는 InvalidPage 예외 발생 (직접 처리 필요)

    since = timezone.now() - timedelta(hours=24)
    # 통계 카드용 24h 컷오프
    stats = {
    # 5개 카드 통계 — 카드 개선: 기존 4개 → 5개 (info 추가로 산술 일관성 확보)
        "total":    Alarm.objects.count(),
        # 전체 누적 알람 수
        "danger":   Alarm.objects.filter(alarm_level__in=["danger", "critical"]).count(),
        # 위험+심각 합산 — get_queryset()/stats action과 동일 정책
        "caution":  Alarm.objects.filter(alarm_level="caution").count(),
        "info":     Alarm.objects.filter(alarm_level="info").count(),
        # info(회복) 알람 — 약 50% 비중인데 기존엔 카드에 없어 안 보였음
        # 이제 '전체 = 위험 + 주의 + 정보'로 산술 일관성 성립
        "last_24h": Alarm.objects.filter(created_at__gte=since).count(),
        # ⚠️ COUNT 쿼리 5번 별도 실행 — 페이지 로드마다 5번씩 풀스캔
        #    개선안: 1번의 aggregate(Count(Case(When(...))))로 통합
        #    또는 created_at에 인덱스 추가 + 별도 캐시 (5초 TTL)
    }

    return render(request, "alerts/alarm_list.html", {
        "alarms":       alarms,
        # 페이지네이션된 알람 객체 (.object_list, .has_next, .number 등 템플릿에서 사용)
        "level_filter": level_filter,
        # 현재 활성 필터 탭 표시용
        "stats":        stats,
        # 상단 5개 카드 데이터
    })