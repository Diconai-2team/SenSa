/* ═══════════════════════════════════════════════════════════════
   R&D 시나리오 패널 JS (Phase J — 확산 모델 기반)

   백엔드 API 호출:
     POST /dashboard/api/scenarios/op/run/<name>/
     POST /dashboard/api/scenarios/op/cleanup/

   Phase J 응답 dict 차이:
     - source_sensor (누출원 1개)
     - leak_elapsed_sec (누출 진행 시간)
     - diffusion_radius_px (확산 반경)
     - affected_sensors [{device_id, distance_px, spike_value, ...}]
     - affected_count
     - zone_polygon_type ('circle' | 'convex_hull')
   ═══════════════════════════════════════════════════════════════ */


function getCsrfToken() {
    const m = document.cookie.match(/csrftoken=([^;]+)/);
    return m ? m[1] : '';
}


function setRdStatus(text, cls = '') {
    const el = document.getElementById('rd-scenario-status');
    if (!el) return;
    el.textContent = text;
    el.className = '';
    if (cls) el.classList.add(cls);
}


async function runRdScenario(name, btnEl) {
    const allBtns = document.querySelectorAll('.rd-scenario-btn');
    allBtns.forEach(b => b.disabled = true);
    if (btnEl) btnEl.classList.add('running');

    setRdStatus(`▶ ${name} 실행 중...`, 'running');

    try {
        const res = await fetch(`/dashboard/api/scenarios/op/run/${name}/`, {
            method: 'POST',
            headers: {
                'X-CSRFToken':    getCsrfToken(),
                'Content-Type':   'application/json',
                'Accept':         'application/json',
            },
            credentials: 'same-origin',
        });

        const data = await res.json();

        if (!res.ok || data.status !== 'success') {
            setRdStatus(
                `✗ 실패: ${data.error || res.status}`,
                'error',
            );
            return;
        }

        // Phase J: 확산 모델 기반 응답
        const source = data.source_sensor;
        const elapsed = data.leak_elapsed_sec;
        const radius = data.diffusion_radius_px;
        const gas = (data.gas || '?').toUpperCase();
        const count = data.affected_count;
        const polyType = data.zone_polygon_type === 'convex_hull'
            ? '다각형 (convex hull)' : '원형';

        // 영향 sensor 거리 요약 (최대 4개만)
        const affected = data.affected_sensors || [];
        const top = affected.slice(0, 4).map(a => {
            return `    ${a.device_id} d=${a.distance_px}px spike=${a.spike_value}ppm`;
        }).join('\n');
        const more = affected.length > 4 ? `\n    ... (+${affected.length-4})` : '';

        setRdStatus(
            `✓ ${name} OK\n` +
            `  누출원: ${source} (${gas}, ${elapsed}초 진행)\n` +
            `  확산 반경: ${radius}px\n` +
            `  영향 sensor: ${count}개 → ${polyType} zone\n` +
            top + more + '\n' +
            `  ${data.zone_ttl_sec}초 후 자연 만료`,
            'success',
        );

    } catch (e) {
        setRdStatus(`✗ 네트워크 오류: ${e.message}`, 'error');
    } finally {
        allBtns.forEach(b => b.disabled = false);
        if (btnEl) btnEl.classList.remove('running');
    }
}


async function cleanupRdScenarios(btnEl) {
    if (btnEl) btnEl.disabled = true;
    setRdStatus('▶ 정리 중...', 'running');

    try {
        const res = await fetch('/dashboard/api/scenarios/op/cleanup/', {
            method: 'POST',
            headers: {
                'X-CSRFToken':    getCsrfToken(),
                'Content-Type':   'application/json',
                'Accept':         'application/json',
            },
            credentials: 'same-origin',
        });

        const data = await res.json();

        if (!res.ok) {
            setRdStatus(`✗ 정리 실패: ${data.error || res.status}`, 'error');
            return;
        }

        setRdStatus(
            `✓ 정리 완료\n` +
            `  zone 삭제: ${data.deleted_zones}\n` +
            `  (sensor 데이터는 5분 후 자연 회복)`,
            'success',
        );
    } catch (e) {
        setRdStatus(`✗ 네트워크 오류: ${e.message}`, 'error');
    } finally {
        if (btnEl) btnEl.disabled = false;
    }
}
