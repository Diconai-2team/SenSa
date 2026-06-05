"""
geofence/events.py — Zone 라이프사이클 이벤트 발행.

[설계]
- zone_lifecycle.py 의 각 라이프사이클 지점에서 호출됨
- DB 에 ZoneEvent 기록 (Phase I-1)
- WebSocket 푸시 — dashboard.zones 그룹으로 발행 (Phase I-2)
- 외부 채널 알림 (Slack/Discord) — critical 승격 시 (Phase I-4)

[안전성]
- 이벤트 기록 / WebSocket 푸시 / 외부 알림 모두 라이프사이클 로직과 격리
- 실패해도 zone 생성·승격은 정상 (try/except 로 흡수)
"""
import logging

from geofence.models import ZoneEvent


logger = logging.getLogger('geofence.events')


def _emit(zone, event_type: str, **kwargs) -> ZoneEvent | None:
    """단일 진입점. DB 기록 + 로그 + WebSocket 푸시.

    Returns:
        생성된 ZoneEvent (실패 시 None).
    """
    try:
        event = ZoneEvent.objects.create(
            zone=zone,
            event_type=event_type,
            from_tier=kwargs.get('from_tier', '') or '',
            to_tier=kwargs.get('to_tier', '') or '',
            trigger_source=kwargs.get('trigger_source', '') or zone.trigger_source,
            detail=kwargs.get('detail') or {},
        )
    except Exception as e:
        logger.error(f"ZoneEvent 기록 실패: zone={zone.id} type={event_type} err={e}")
        return None

    logger.info(
        f"[zone={zone.id}] {event_type} "
        f"tier={kwargs.get('from_tier', '?')}->{kwargs.get('to_tier', zone.tier)} "
        f"source={zone.trigger_source}"
    )

    # [Phase I-2] WebSocket 푸시 — 실패해도 라이프사이클 영향 없게 try/except
    try:
        from realtime.publishers import publish_zone_event
        publish_zone_event({
            'event_id': event.id,
            'event_type': event.event_type,
            'zone_id': zone.id,
            'zone_name': zone.name,
            'from_tier': event.from_tier,
            'to_tier': event.to_tier or zone.tier,
            'trigger_source': event.trigger_source,
            'detail': event.detail,
            'created_at': event.created_at.isoformat(),
            # [Live 갱신] frontend 가 새로고침 없이 polygon 그릴 수 있도록 필수 정보 포함
            'polygon': zone.polygon,
            'zone_type': zone.zone_type,
            'risk_level': zone.risk_level,
            'tier': zone.tier,
            'is_dynamic': zone.is_dynamic,
        })
        logger.debug(f"[zone={zone.id}] WebSocket 푸시 완료 ({event_type})")
    except Exception as e:
        logger.warning(f"WebSocket 푸시 실패 (라이프사이클은 정상): {e}")

    # [Phase I-4] 외부 채널 알림 — critical 승격 이벤트만 (소음 방지)
    if event_type == 'upgraded_to_critical':
        _notify_external_critical(zone, kwargs)

    # [Phase I-4b] 외부 채널 알림 — 동적 '위험' 구역 생성(=위험 요소 발생) 시 1회.
    #   on_zone_created 가 zone 당 1회만 호출되므로 자연히 1회. 정적 zone·caution 은 제외.
    if (event_type == 'created'
            and getattr(zone, 'is_dynamic', False)
            and zone.zone_type in ('danger', 'restricted')):
        _notify_external_zone_created(zone, kwargs)

    # [P4-C 8차] zone 이벤트 메트릭 — 라이프사이클 누적
    try:
        from geofence.metrics import zone_event_total
        zone_event_total.labels(event_type=event_type).inc()
    except Exception:
        pass  # 메트릭 실패가 라이프사이클을 끊지 않도록 격리

    return event


def _notify_external_critical(zone, kwargs: dict) -> None:
    """[Phase I-4] critical 승격 시 Slack/Discord 알림 큐잉.

    실패해도 라이프사이클 영향 없도록 모든 예외 흡수.
    """
    try:
        from alerts.notifiers import is_configured
        if not is_configured():
            return     # webhook 미설정 시 skip

        from alerts.tasks import send_external_notification_task

        tier_label = {
            'tentative': '잠정',
            'confirmed': '확인',
            'critical':  '긴급',
        }.get(zone.tier, zone.tier or '?')

        trigger_label = {
            'ttm_anomaly':  '실측',
            'ttm_forecast': '사전경고',
            'threshold':    '임계초과',
            'manual':       '수동',
        }.get(zone.trigger_source, zone.trigger_source or '?')

        title = f"Zone 긴급 승격 — {zone.name}"
        message = (
            f"가스: {zone.gas_type.upper() if zone.gas_type else '?'}\n"
            f"승격: {kwargs.get('from_tier', '?')} → {tier_label}\n"
            f"발동: {trigger_label}\n"
            f"확인 센서: {zone.confirmed_devices.count()}개\n"
            f"반경: {zone.current_radius_px:.0f}px"
        )

        _res = send_external_notification_task.delay(
            title=title,
            message=message,
            severity='critical',
        )
        logger.info(f"[zone={zone.id}] 외부 알림 task 큐잉: task_id={_res.id}")
    except Exception as e:
        logger.warning(f"외부 알림 큐잉 실패 (라이프사이클은 정상): {e}")


def _notify_external_zone_created(zone, kwargs: dict) -> None:
    """[Phase I-4b] 동적 위험구역 생성 시 외부 알림(디스코드) 큐잉.

    '위험 요소 발생 자체'를 작업자에게 1회 통지. critical 발송과 동일 정책
    (webhook 미설정 시 skip, 모든 예외 흡수 → 라이프사이클 영향 없음).
    """
    try:
        from alerts.notifiers import is_configured
        if not is_configured():
            return

        from alerts.tasks import send_external_notification_task

        # zone_type → severity(이모지) 매핑
        severity = {'restricted': 'critical', 'danger': 'danger',
                    'caution': 'caution'}.get(zone.zone_type, 'danger')

        trigger_label = {
            'ttm_anomaly':  '실측 이상',
            'ttm_forecast': '사전경고',
            'threshold':    '임계초과',
            'manual':       '수동',
        }.get(zone.trigger_source, zone.trigger_source or '?')

        title = f"위험구역 발생 — {zone.name}"
        message = (
            f"가스: {zone.gas_type.upper() if zone.gas_type else '?'}\n"
            f"등급: {zone.zone_type}\n"
            f"발동: {trigger_label}\n"
            f"초기 반경: {zone.current_radius_px:.0f}px"
            if zone.current_radius_px else
            f"가스: {zone.gas_type.upper() if zone.gas_type else '?'}\n"
            f"등급: {zone.zone_type}\n"
            f"발동: {trigger_label}"
        )

        _res = send_external_notification_task.delay(
            title=title,
            message=message,
            severity=severity,
        )
        logger.info(f"[zone={zone.id}] 위험구역 발생 외부 알림 큐잉: task_id={_res.id}")
    except Exception as e:
        logger.warning(f"위험구역 발생 외부 알림 큐잉 실패 (라이프사이클은 정상): {e}")


# ─────────────────────────────────────────
# 라이프사이클 이벤트 발행 함수
# ─────────────────────────────────────────

def on_zone_created(zone) -> ZoneEvent | None:
    """동적 zone 생성 직후 호출."""
    return _emit(
        zone, 'created',
        to_tier=zone.tier,
        detail={
            'source_device': zone.source_device.device_id if zone.source_device else None,
            'gas_type': zone.gas_type,
            'initial_radius_px': zone.current_radius_px,
        },
    )


def on_tier_upgraded(zone, from_tier: str, to_tier: str) -> ZoneEvent | None:
    """tentative → confirmed / confirmed → critical 등 승격 직후."""
    event_type = f'upgraded_to_{to_tier}'
    return _emit(
        zone, event_type,
        from_tier=from_tier,
        to_tier=to_tier,
        detail={
            'confirmed_devices_count': zone.confirmed_devices.count(),
            'radius_px': zone.current_radius_px,
        },
    )


def on_polygon_expanded(zone, added_device_ids: list) -> ZoneEvent | None:
    """confirmed_devices 추가로 polygon 재생성 시."""
    return _emit(
        zone, 'polygon_expanded',
        to_tier=zone.tier,
        detail={
            'added_devices': added_device_ids,
            'total_confirmed': zone.confirmed_devices.count(),
        },
    )


def on_zone_expired(zone) -> ZoneEvent | None:
    """TTL 만료로 is_active=False 전환 시."""
    return _emit(
        zone, 'expired',
        from_tier=zone.tier,
        detail={
            'lifetime_sec': (
                (zone.last_updated_at - zone.created_at).total_seconds()
                if zone.last_updated_at and zone.created_at else None
            ),
        },
    )
