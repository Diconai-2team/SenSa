/* 백오피스 — 설비/장비 관리 */
(function () {
    'use strict';
    const modal = document.getElementById('bo-device-modal');
    const form  = document.getElementById('bo-device-form');
    const tbody = document.querySelector('#bo-device-table tbody');
    const checkAll = document.getElementById('bo-check-all');
    const btnDel = document.getElementById('bo-bulk-delete');
    const btnOn  = document.getElementById('bo-bulk-on');
    const btnOff = document.getElementById('bo-bulk-off');

    function setMode(mode) {
        modal.dataset.mode = mode;
        modal.querySelectorAll('[data-create-only]').forEach(el => el.style.display = (mode==='create'?'':'none'));
        modal.querySelectorAll('[data-edit-only]').forEach(el => el.style.display = (mode==='edit'?'':'none'));
    }
    function open(mode) { setMode(mode); modal.classList.add('is-open'); document.body.style.overflow='hidden'; }
    function close() {
        modal.classList.remove('is-open'); document.body.style.overflow='';
        form.reset(); BO.showFormErrors(form, {}); form.querySelector('[name="id"]').value='';
        form.querySelector('[name="device_id"]').readOnly = false;
    }

    document.querySelector('[data-open-create-modal]').addEventListener('click', () => {
        form.querySelector('[name="is_active"]').checked = true;
        open('create');
    });
    modal.addEventListener('click', e => {
        if (e.target === modal || e.target.matches('[data-close-modal]')) close();
    });
    document.addEventListener('keydown', e => {
        if (e.key === 'Escape' && modal.classList.contains('is-open')) close();
    });

    tbody.addEventListener('click', async e => {
        const btn = e.target.closest('[data-edit]');
        if (!btn) return;
        const { ok, data } = await BO.fetchJSON(`/backoffice/api/devices/${btn.dataset.edit}/`);
        if (!ok) { BO.toast('정보를 불러오지 못했습니다.', 'error'); return; }
        const d = data.device;
        form.querySelector('[name="id"]').value = d.id;
        form.querySelector('[name="device_id"]').value = d.device_id;
        form.querySelector('[name="device_id"]').readOnly = true;
        form.querySelector('[name="device_name"]').value = d.device_name;
        form.querySelector('[name="sensor_type"]').value = d.sensor_type;
        form.querySelector('[name="geofence_id"]').value = d.geofence_id || '';
        form.querySelector('[name="x"]').value = d.x;
        form.querySelector('[name="y"]').value = d.y;
        form.querySelector('[name="last_value_unit"]').value = d.last_value_unit || '';
        form.querySelector('[name="is_active"]').checked = !!d.is_active;
        BO.showFormErrors(form, {});
        open('edit');
    });

    form.addEventListener('submit', async e => {
        e.preventDefault();
        BO.showFormErrors(form, {});
        const fd = new FormData(form);
        const payload = Object.fromEntries(fd.entries());
        payload.is_active = form.querySelector('[name="is_active"]').checked ? 'on' : '';
        const isEdit = modal.dataset.mode === 'edit';
        const url = isEdit
            ? `/backoffice/api/devices/${payload.id}/update/`
            : `/backoffice/api/devices/create/`;
        const { ok, status, data } = await BO.fetchJSON(url, { method:'POST', body:JSON.stringify(payload) });
        if (!ok) {
            if (status === 400 && data.errors) {
                BO.showFormErrors(form, data.errors);
                BO.toast('입력값을 확인해 주세요.', 'error');
            } else BO.toast(data.error || '저장 실패', 'error');
            return;
        }
        BO.toast(isEdit ? '수정되었습니다.' : '등록되었습니다.', 'success');
        close();
        setTimeout(() => location.reload(), 400);
    });

    function selectedIds() {
        return Array.from(tbody.querySelectorAll('.bo-row-check:checked')).map(c => parseInt(c.value, 10));
    }
    function refresh() {
        const has = selectedIds().length > 0;
        btnDel.disabled = !has; btnOn.disabled = !has; btnOff.disabled = !has;
        tbody.querySelectorAll('tr').forEach(tr => {
            const c = tr.querySelector('.bo-row-check');
            tr.classList.toggle('is-selected', c && c.checked);
        });
    }
    tbody.addEventListener('change', e => {
        if (e.target.classList.contains('bo-row-check')) refresh();
    });
    checkAll.addEventListener('change', () => {
        tbody.querySelectorAll('.bo-row-check').forEach(c => c.checked = checkAll.checked);
        refresh();
    });

    async function bulk(url, body, msg) {
        const res = await BO.fetchJSON(url, { method:'POST', body: JSON.stringify(body) });
        if (!res.ok) { BO.toast(res.data.error || '실패', 'error'); return; }
        BO.toast(msg, 'success');
        setTimeout(() => location.reload(), 400);
    }
    btnDel.addEventListener('click', async () => {
        const ids = selectedIds();
        if (!ids.length) return;
        if (!await BO.confirm(`선택한 ${ids.length}건을 삭제하시겠습니까?`)) return;
        bulk('/backoffice/api/devices/bulk-delete/', { ids }, '삭제되었습니다.');
    });
    btnOn.addEventListener('click', () => {
        const ids = selectedIds();
        if (!ids.length) return;
        bulk('/backoffice/api/devices/bulk-toggle/', { ids, is_active: true }, '활성화되었습니다.');
    });
    btnOff.addEventListener('click', () => {
        const ids = selectedIds();
        if (!ids.length) return;
        bulk('/backoffice/api/devices/bulk-toggle/', { ids, is_active: false }, '비활성화되었습니다.');
    });

    refresh();
    setMode('create');

    // ── v5: 자동 매핑 ──
    document.getElementById('bo-auto-map').addEventListener('click', async () => {
        const ok = await BO.confirm('모든 장비의 지오펜스를 좌표 기준으로 다시 계산합니다.\n계속하시겠습니까?');
        if (!ok) return;
        const res = await BO.fetchJSON('/backoffice/api/devices/auto-map/', { method:'POST' });
        if (!res.ok) { BO.toast(res.data.error || '실패', 'error'); return; }
        BO.toast(`${res.data.mapped}건 매핑 / ${res.data.cleared}건 해제`, 'success');
        setTimeout(() => location.reload(), 600);
    });

    // ── v5: CSV 업로드 (v6: upsert 모드 추가) ──
    let csvMode = 'create';
    const csvToggleBtn = document.getElementById('bo-csv-toggle');
    const csvMenu = document.getElementById('bo-csv-menu');
    csvToggleBtn.addEventListener('click', e => {
        e.stopPropagation();
        csvMenu.style.display = csvMenu.style.display === 'none' ? 'block' : 'none';
    });
    document.addEventListener('click', () => { csvMenu.style.display = 'none'; });
    document.querySelectorAll('.bo-csv-trigger').forEach(btn => {
        btn.addEventListener('click', e => {
            e.stopPropagation();
            csvMode = btn.dataset.mode;
            csvMenu.style.display = 'none';
            document.getElementById('bo-csv-input').click();
        });
    });

    document.getElementById('bo-csv-input').addEventListener('change', async (e) => {
        const file = e.target.files[0];
        if (!file) return;
        const fd = new FormData();
        fd.append('file', file);
        fd.append('mode', csvMode);
        const res = await fetch('/backoffice/api/devices/csv-upload/', {
            method: 'POST',
            credentials: 'same-origin',
            headers: { 'X-CSRFToken': BO.csrfToken },
            body: fd,
        });
        const data = await res.json();
        if (!res.ok) {
            BO.toast(data.error || 'CSV 업로드 실패', 'error');
            return;
        }
        let parts = [`등록 ${data.created}건`];
        if (data.updated !== undefined) parts.push(`수정 ${data.updated}건`);
        parts.push(`건너뜀 ${data.skipped}건`);
        if (data.error_count) parts.push(`오류 ${data.error_count}건`);
        BO.toast(parts.join(', '), data.error_count ? 'error' : 'success');
        e.target.value = '';
        setTimeout(() => location.reload(), 800);
    });

    // ── v6: 장비 변경 이력 모달 ──
    const historyModal = document.getElementById('bo-history-modal');
    historyModal.addEventListener('click', e => {
        if (e.target === historyModal || e.target.matches('[data-close-modal]')) {
            historyModal.classList.remove('is-open');
            document.body.style.overflow = '';
        }
    });
    tbody.addEventListener('click', async e => {
        const btn = e.target.closest('[data-history]');
        if (!btn) return;
        const id = btn.dataset.history;
        const deviceId = btn.dataset.deviceId;
        const { ok, data } = await BO.fetchJSON(`/backoffice/api/devices/${id}/history/`);
        if (!ok) { BO.toast('이력을 불러오지 못했습니다.', 'error'); return; }
        document.getElementById('bo-history-device').textContent = `${deviceId} (${data.device.device_name})`;
        const body = document.getElementById('bo-history-body');
        body.innerHTML = data.history.map(h => `
            <tr>
                <td>${h.created_at}</td>
                <td><span class="bo-badge">${h.action_display}</span></td>
                <td>${h.actor}</td>
                <td>
                    ${h.message ? `<div style="font-size:12px;color:var(--bo-text-muted);margin-bottom:4px;">${escapeHtml(h.message)}</div>` : ''}
                    ${Object.keys(h.changes || {}).length ? `<pre style="margin:0;padding:6px;background:var(--bo-bg);border-radius:4px;font-size:11px;max-width:500px;overflow:auto;">${escapeHtml(JSON.stringify(h.changes, null, 2))}</pre>` : '<span class="bo-text-subtle">-</span>'}
                </td>
            </tr>
        `).join('') || `<tr><td colspan="4" class="bo-table-empty">변경 이력이 없습니다.</td></tr>`;
        historyModal.classList.add('is-open');
        document.body.style.overflow = 'hidden';
    });

    function escapeHtml(s) {
        if (s == null) return '';
        return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;').replace(/'/g,'&#39;');
    }
})();
