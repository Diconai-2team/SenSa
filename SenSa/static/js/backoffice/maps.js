/* ============================================================
   백오피스 — 지도 편집 JS (캔버스 + 폴리곤 그리기)
   ============================================================ */
(function () {
    'use strict';

    const BOOT = window.BO_MAP_BOOTSTRAP || { map: null, geofences: [], devices: [] };

    const canvas = document.getElementById('bo-canvas');
    const ctx    = canvas.getContext('2d');
    const W = canvas.width, H = canvas.height;

    const list      = document.getElementById('bo-gf-list');
    const btnAdd    = document.getElementById('bo-gf-add');
    const btnSelect = document.getElementById('bo-tool-select');
    const btnDraw   = document.getElementById('bo-tool-draw');
    const btnClear  = document.getElementById('bo-tool-clear');

    const modal = document.getElementById('bo-gf-modal');
    const form  = document.getElementById('bo-gf-form');
    const btnDelete = document.getElementById('bo-gf-delete');

    let mode = 'select';   // 'select' | 'draw'
    let drawing = [];      // 그리기 중인 점들
    let mapImg = null;

    // v6 — 폴리곤 점 드래그 편집
    let selectedGfId = null;       // 선택된 지오펜스 id
    let dragging = null;           // {gfId, vertexIdx} 또는 null
    let dragHasMoved = false;      // 실제로 움직였는지 (mouseup 시 저장 결정)

    const ZONE_FILL = {
        danger:     'rgba(239, 68, 68, 0.30)',
        caution:    'rgba(245, 158, 11, 0.30)',
        restricted: 'rgba(107, 114, 128, 0.40)',
    };
    const ZONE_STROKE = {
        danger:     '#ef4444',
        caution:    '#f59e0b',
        restricted: '#9ca3af',
    };
    const SENSOR_COLOR = {
        gas:    '#10b981',
        power:  '#3b82f6',
        motion: '#a855f7',
        temperature: '#f97316',
    };

    if (BOOT.map) {
        mapImg = new Image();
        mapImg.onload = render;
        mapImg.src = BOOT.map.url;
    } else {
        render();
    }

    function setMode(newMode) {
        mode = newMode;
        btnSelect.classList.toggle('is-active', mode === 'select');
        btnDraw.classList.toggle('is-active', mode === 'draw');
        canvas.style.cursor = mode === 'draw' ? 'crosshair' : 'default';
        if (mode !== 'draw') drawing = [];
        render();
    }

    function render() {
        // 배경
        ctx.fillStyle = '#0b0f17';
        ctx.fillRect(0, 0, W, H);
        if (mapImg && mapImg.complete) {
            ctx.drawImage(mapImg, 0, 0, W, H);
            ctx.fillStyle = 'rgba(11, 15, 23, 0.55)';
            ctx.fillRect(0, 0, W, H);
        } else {
            // 그리드 (지도 없을 때 좌표 가이드)
            ctx.strokeStyle = 'rgba(255,255,255,0.05)';
            ctx.lineWidth = 1;
            for (let x = 0; x <= W; x += 100) {
                ctx.beginPath(); ctx.moveTo(x, 0); ctx.lineTo(x, H); ctx.stroke();
            }
            for (let y = 0; y <= H; y += 100) {
                ctx.beginPath(); ctx.moveTo(0, y); ctx.lineTo(W, y); ctx.stroke();
            }
        }

        // 지오펜스
        BOOT.geofences.forEach(g => {
            drawPolygon(g.polygon, g.zone_type, g.name);
            // v6 — 선택된 폴리곤은 점 핸들 표시 (드래그 가능)
            if (selectedGfId === g.id && mode === 'select') {
                g.polygon.forEach((p, idx) => {
                    const isDragging = dragging && dragging.gfId === g.id && dragging.vertexIdx === idx;
                    ctx.fillStyle = isDragging ? '#fbbf24' : '#ffffff';
                    ctx.strokeStyle = '#1a73e8';
                    ctx.lineWidth = 2;
                    ctx.beginPath();
                    ctx.arc(p[0], p[1], 7, 0, Math.PI * 2);
                    ctx.fill();
                    ctx.stroke();
                });
            }
        });

        // 그리는 중 폴리곤
        if (drawing.length > 0) {
            ctx.fillStyle = 'rgba(26, 115, 232, 0.25)';
            ctx.strokeStyle = 'var(--bo-primary)'.startsWith('var') ? '#1a73e8' : '#1a73e8';
            ctx.lineWidth = 2;
            ctx.setLineDash([4, 4]);
            ctx.beginPath();
            ctx.moveTo(drawing[0][0], drawing[0][1]);
            for (let i = 1; i < drawing.length; i++) ctx.lineTo(drawing[i][0], drawing[i][1]);
            ctx.stroke();
            ctx.setLineDash([]);
            drawing.forEach((p, i) => {
                ctx.fillStyle = i === 0 ? '#fbbf24' : '#1a73e8';
                ctx.beginPath();
                ctx.arc(p[0], p[1], 6, 0, Math.PI * 2);
                ctx.fill();
            });
        }

        // 장비 마커
        BOOT.devices.forEach(d => {
            ctx.fillStyle = SENSOR_COLOR[d.sensor_type] || '#94a3b8';
            ctx.strokeStyle = '#fff';
            ctx.lineWidth = 2;
            ctx.beginPath();
            ctx.arc(d.x, d.y, 8, 0, Math.PI * 2);
            ctx.fill();
            ctx.stroke();
            // 라벨
            ctx.fillStyle = '#fff';
            ctx.font = '11px sans-serif';
            ctx.fillText(d.device_id, d.x + 12, d.y + 4);
        });
    }

    function drawPolygon(poly, zone_type, name) {
        if (!poly || poly.length < 3) return;
        ctx.fillStyle = ZONE_FILL[zone_type] || ZONE_FILL.danger;
        ctx.strokeStyle = ZONE_STROKE[zone_type] || ZONE_STROKE.danger;
        ctx.lineWidth = 2;
        ctx.beginPath();
        ctx.moveTo(poly[0][0], poly[0][1]);
        for (let i = 1; i < poly.length; i++) ctx.lineTo(poly[i][0], poly[i][1]);
        ctx.closePath();
        ctx.fill();
        ctx.stroke();
        // 라벨
        let cx = 0, cy = 0;
        poly.forEach(p => { cx += p[0]; cy += p[1]; });
        cx /= poly.length; cy /= poly.length;
        ctx.fillStyle = '#fff';
        ctx.font = 'bold 12px sans-serif';
        ctx.textAlign = 'center';
        ctx.fillText(name, cx, cy);
        ctx.textAlign = 'start';
    }

    function getCanvasCoords(e) {
        const rect = canvas.getBoundingClientRect();
        const sx = canvas.width / rect.width;
        const sy = canvas.height / rect.height;
        return {
            x: Math.round((e.clientX - rect.left) * sx),
            y: Math.round((e.clientY - rect.top) * sy),
        };
    }

    function findVertexAt(x, y) {
        if (selectedGfId === null) return null;
        const gf = BOOT.geofences.find(g => g.id === selectedGfId);
        if (!gf) return null;
        const HIT = 12;
        for (let i = 0; i < gf.polygon.length; i++) {
            const p = gf.polygon[i];
            const dx = x - p[0], dy = y - p[1];
            if (Math.sqrt(dx*dx + dy*dy) <= HIT) {
                return { gfId: gf.id, vertexIdx: i };
            }
        }
        return null;
    }

    canvas.addEventListener('mousedown', e => {
        if (mode !== 'select') return;
        const { x, y } = getCanvasCoords(e);
        const hit = findVertexAt(x, y);
        if (hit) {
            dragging = hit;
            dragHasMoved = false;
            canvas.style.cursor = 'grabbing';
        }
    });

    canvas.addEventListener('mousemove', e => {
        if (mode !== 'select') return;
        const { x, y } = getCanvasCoords(e);

        if (dragging) {
            const gf = BOOT.geofences.find(g => g.id === dragging.gfId);
            if (gf) {
                gf.polygon[dragging.vertexIdx] = [x, y];
                dragHasMoved = true;
                render();
            }
        } else {
            // hover — vertex 위면 cursor=grab
            const hit = findVertexAt(x, y);
            canvas.style.cursor = hit ? 'grab' : 'default';
        }
    });

    canvas.addEventListener('mouseup', async () => {
        if (!dragging) return;
        const dragInfo = dragging;
        dragging = null;
        canvas.style.cursor = 'default';
        if (!dragHasMoved) { render(); return; }

        // 서버 저장 — polygon 만 갱신 (다른 필드는 그대로)
        const gf = BOOT.geofences.find(g => g.id === dragInfo.gfId);
        if (!gf) return;
        // 전체 detail 받아서 polygon 만 바꿔 다시 보냄 (다른 필드 유지)
        try {
            const detail = await BO.fetchJSON(`/backoffice/api/geofences/${gf.id}/`);
            if (!detail.ok) throw new Error('detail load failed');
            const g = detail.data.geofence;
            const payload = {
                name: g.name,
                zone_type: g.zone_type,
                risk_level: g.risk_level,
                description: g.description || '',
                polygon_json: JSON.stringify(gf.polygon),
                is_active: g.is_active ? 'on' : '',
            };
            const res = await BO.fetchJSON(`/backoffice/api/geofences/${gf.id}/update/`, {
                method: 'POST', body: JSON.stringify(payload),
            });
            if (!res.ok) {
                BO.toast(res.data.error || '저장 실패', 'error');
            } else {
                BO.toast('점 위치가 저장되었습니다.', 'success');
            }
        } catch (err) {
            BO.toast('저장 중 오류 발생', 'error');
        }
        render();
    });

    canvas.addEventListener('click', e => {
        if (dragHasMoved) { dragHasMoved = false; return; }   // 드래그 후 click 무시
        const { x, y } = getCanvasCoords(e);

        if (mode === 'draw') {
            // 첫 점 근처 클릭 → 도형 닫기
            if (drawing.length >= 3) {
                const dx = x - drawing[0][0], dy = y - drawing[0][1];
                if (Math.sqrt(dx*dx + dy*dy) < 14) {
                    finishDrawing();
                    return;
                }
            }
            drawing.push([x, y]);
            render();
        }
    });

    function finishDrawing() {
        if (drawing.length < 3) return;
        const points = drawing.slice();
        drawing = [];
        setMode('select');
        // 모달 열기
        form.reset();
        BO.showFormErrors(form, {});
        form.querySelector('[name="id"]').value = '';
        form.querySelector('[name="polygon_json"]').value = JSON.stringify(points);
        form.querySelector('[name="is_active"]').checked = true;
        setModalMode('create');
        openModal();
    }

    btnSelect.addEventListener('click', () => setMode('select'));
    btnDraw.addEventListener('click', () => setMode('draw'));
    btnClear.addEventListener('click', () => { drawing = []; render(); });

    btnAdd.addEventListener('click', () => {
        form.reset();
        BO.showFormErrors(form, {});
        form.querySelector('[name="id"]').value = '';
        form.querySelector('[name="polygon_json"]').value = '';
        form.querySelector('[name="is_active"]').checked = true;
        setModalMode('create');
        openModal();
    });

    list.addEventListener('click', async e => {
        const li = e.target.closest('li[data-id]');
        if (!li) return;
        const id = parseInt(li.dataset.id, 10);
        list.querySelectorAll('li').forEach(x => x.classList.remove('is-active'));
        li.classList.add('is-active');

        // v6 — 드래그 편집을 위한 폴리곤 선택. 모달 없이 점만 표시.
        selectedGfId = id;
        render();

        // 더블클릭이 아니면 편집 모달 열지 않음 → 폴리곤 점만 보이게
        // 사용자가 [편집] 버튼 클릭 시에만 모달
        const btnEdit = li.querySelector('[data-edit-btn]');
        if (e.target !== btnEdit) return;

        const { ok, data } = await BO.fetchJSON(`/backoffice/api/geofences/${id}/`);
        if (!ok) { BO.toast('지오펜스 정보를 불러오지 못했습니다.', 'error'); return; }
        const g = data.geofence;
        form.querySelector('[name="id"]').value = g.id;
        form.querySelector('[name="name"]').value = g.name;
        form.querySelector('[name="zone_type"]').value = g.zone_type;
        form.querySelector('[name="risk_level"]').value = g.risk_level;
        form.querySelector('[name="description"]').value = g.description || '';
        form.querySelector('[name="polygon_json"]').value = JSON.stringify(g.polygon);
        form.querySelector('[name="is_active"]').checked = !!g.is_active;
        BO.showFormErrors(form, {});
        setModalMode('edit');
        openModal();
    });

    function setModalMode(m) {
        modal.dataset.mode = m;
        modal.querySelectorAll('[data-create-only]').forEach(el => el.style.display = (m==='create'?'':'none'));
        modal.querySelectorAll('[data-edit-only]').forEach(el => el.style.display = (m==='edit'?'':'none'));
    }
    function openModal() { modal.classList.add('is-open'); document.body.style.overflow='hidden'; }
    function closeModal() { modal.classList.remove('is-open'); document.body.style.overflow=''; }

    modal.addEventListener('click', e => {
        if (e.target === modal || e.target.matches('[data-close-modal]')) closeModal();
    });
    document.addEventListener('keydown', e => {
        if (e.key === 'Escape' && modal.classList.contains('is-open')) closeModal();
    });

    form.addEventListener('submit', async e => {
        e.preventDefault();
        BO.showFormErrors(form, {});
        const fd = new FormData(form);
        const payload = Object.fromEntries(fd.entries());
        payload.is_active = form.querySelector('[name="is_active"]').checked ? 'on' : '';
        const isEdit = modal.dataset.mode === 'edit';
        const url = isEdit
            ? `/backoffice/api/geofences/${payload.id}/update/`
            : `/backoffice/api/geofences/create/`;
        const { ok, status, data } = await BO.fetchJSON(url, { method:'POST', body:JSON.stringify(payload) });
        if (!ok) {
            if (status === 400 && data.errors) {
                BO.showFormErrors(form, data.errors);
                BO.toast('입력값을 확인해 주세요.', 'error');
            } else BO.toast(data.error || '저장 실패', 'error');
            return;
        }
        BO.toast(isEdit ? '수정되었습니다.' : '등록되었습니다.', 'success');
        closeModal();
        setTimeout(() => location.reload(), 400);
    });

    btnDelete.addEventListener('click', async () => {
        const id = form.querySelector('[name="id"]').value;
        if (!id) return;
        if (!await BO.confirm('이 지오펜스를 삭제하시겠습니까?')) return;
        const res = await BO.fetchJSON(`/backoffice/api/geofences/${id}/delete/`, { method:'POST' });
        if (!res.ok) { BO.toast(res.data.error || '삭제 실패', 'error'); return; }
        BO.toast('삭제되었습니다.', 'success');
        closeModal();
        setTimeout(() => location.reload(), 400);
    });

    setMode('select');
})();
