/* ============================================================
   백오피스 — 임계치 기준 관리 JS
   2-panel: 좌측 분류 → 우측 정보카드 + 임계치 항목 목록
   ============================================================ */
(function () {
    'use strict';

    const treeEl    = document.getElementById('bo-tc-tree');
    const emptyCard = document.getElementById('bo-tc-empty');
    const infoCard  = document.getElementById('bo-tc-info-card');
    const thCard    = document.getElementById('bo-th-card');

    const tcNameEl  = document.getElementById('bo-tc-name');
    const tcCodeEl  = document.getElementById('bo-tc-code');
    const tcCountEl = document.getElementById('bo-tc-count');
    const tcAppEl   = document.getElementById('bo-tc-applies');
    const tcUpdEl   = document.getElementById('bo-tc-updated');

    const thBody    = document.getElementById('bo-th-body');
    const thCheckAll= document.getElementById('bo-th-check-all');
    const thCountEl = document.getElementById('bo-th-count');

    const btnTcAdd  = document.getElementById('bo-tc-add');
    const btnTcEdit = document.getElementById('bo-tc-edit');
    const btnThAdd  = document.getElementById('bo-th-add');
    const btnThDel  = document.getElementById('bo-th-bulk-delete');
    const btnThOff  = document.getElementById('bo-th-toggle-off');
    const btnThOn   = document.getElementById('bo-th-toggle-on');

    const tcModal = document.getElementById('bo-tc-modal');
    const tcForm  = document.getElementById('bo-tc-form');
    const thModal = document.getElementById('bo-th-modal');
    const thForm  = document.getElementById('bo-th-form');

    let currentCat = null;
    let currentItems = [];

    const APPLIES_LABELS = {
        realtime:   '실시간 관제',
        ai_predict: 'AI 예측',
        alarm:      '알림',
    };
    const OPERATOR_LABELS = { over: '초과', under: '이하' };

    function setMode(modal, mode) {
        modal.dataset.mode = mode;
        modal.querySelectorAll('[data-create-only]').forEach(el => el.style.display = (mode==='create'?'':'none'));
        modal.querySelectorAll('[data-edit-only]').forEach(el => el.style.display = (mode==='edit'?'':'none'));
    }
    function open(modal) { modal.classList.add('is-open'); document.body.style.overflow='hidden'; }
    function close(modal) {
        modal.classList.remove('is-open'); document.body.style.overflow='';
        const f = modal.querySelector('form');
        if (f) { f.reset(); BO.showFormErrors(f, {}); }
    }
    document.querySelectorAll('.bo-modal-backdrop').forEach(m => {
        m.addEventListener('click', e => {
            if (e.target === m || e.target.matches('[data-close-modal]')) close(m);
        });
    });
    document.addEventListener('keydown', e => {
        if (e.key === 'Escape') document.querySelectorAll('.bo-modal-backdrop.is-open').forEach(close);
    });

    function fillAppliesCheckboxes(form, csv) {
        const list = (csv || '').split(',').filter(Boolean);
        form.querySelectorAll('[name^="applies_to_"]').forEach(cb => {
            cb.checked = list.includes(cb.value);
        });
    }
    function readAppliesCSV(form) {
        return Array.from(form.querySelectorAll('[name^="applies_to_"]:checked'))
            .map(cb => cb.value).join(',');
    }

    treeEl.addEventListener('click', async e => {
        const li = e.target.closest('li[data-tc-id]');
        if (!li) return;
        await loadCat(parseInt(li.dataset.tcId, 10));
        treeEl.querySelectorAll('li').forEach(x => x.classList.remove('is-active'));
        li.classList.add('is-active');
    });

    async function loadCat(id) {
        const { ok, data } = await BO.fetchJSON(`/backoffice/api/threshold-categories/${id}/`);
        if (!ok) { BO.toast('분류를 불러오지 못했습니다.', 'error'); return; }
        currentCat = data.category;
        currentItems = data.thresholds || [];
        renderCat();
    }

    function renderCat() {
        emptyCard.style.display = 'none';
        infoCard.style.display = '';
        thCard.style.display = '';

        tcNameEl.textContent = currentCat.name;
        tcCodeEl.textContent = currentCat.code;
        tcCountEl.textContent = `${currentCat.threshold_count}건`;
        tcUpdEl.textContent = `${currentCat.updated_at} (${currentCat.updated_by_name})`;

        const pills = (currentCat.applies_to_list || []).map(
            k => `<span class="bo-pill">${APPLIES_LABELS[k] || k}</span>`
        ).join('');
        tcAppEl.innerHTML = pills
            ? `<div class="bo-applies-pills">${pills}</div>`
            : '<span class="bo-text-subtle">미지정</span>';

        renderItems();
    }

    function renderItems() {
        thCountEl.textContent = currentItems.length;
        thBody.innerHTML = currentItems.map(t => {
            const appliesPills = (t.applies_to_list || []).map(
                k => `<span class="bo-pill">${APPLIES_LABELS[k] || k}</span>`
            ).join(' ');
            return `
                <tr data-id="${t.id}">
                    <td><input type="checkbox" class="bo-checkbox bo-row-check" value="${t.id}"></td>
                    <td><code style="font-size:12px;">${escapeHtml(t.item_code)}</code></td>
                    <td>${escapeHtml(t.item_name)}</td>
                    <td>${escapeHtml(t.unit)}</td>
                    <td>${OPERATOR_LABELS[t.operator] || t.operator}</td>
                    <td style="font-variant-numeric:tabular-nums;">${t.caution_value}</td>
                    <td style="font-variant-numeric:tabular-nums;">${t.danger_value}</td>
                    <td><div class="bo-applies-pills">${appliesPills}</div></td>
                    <td>${t.is_active
                        ? '<span class="bo-badge bo-badge-status-active">사용</span>'
                        : '<span class="bo-badge bo-badge-status-disabled">미사용</span>'}</td>
                    <td><button type="button" class="bo-btn bo-btn-sm bo-btn-primary" data-edit="${t.id}">수정</button></td>
                </tr>`;
        }).join('') || `<tr><td colspan="10" class="bo-table-empty">등록된 임계치가 없습니다.</td></tr>`;
        thCheckAll.checked = false;
        refreshBulk();
    }

    function selectedIds() {
        return Array.from(thBody.querySelectorAll('.bo-row-check:checked')).map(c => parseInt(c.value, 10));
    }
    function refreshBulk() {
        const has = selectedIds().length > 0;
        btnThDel.disabled = !has;
        btnThOff.disabled = !has;
        btnThOn.disabled = !has;
        thBody.querySelectorAll('tr').forEach(tr => {
            const c = tr.querySelector('.bo-row-check');
            tr.classList.toggle('is-selected', c && c.checked);
        });
    }
    thBody.addEventListener('change', e => {
        if (e.target.classList.contains('bo-row-check')) refreshBulk();
    });
    thCheckAll.addEventListener('change', () => {
        thBody.querySelectorAll('.bo-row-check').forEach(c => c.checked = thCheckAll.checked);
        refreshBulk();
    });

    // ── 분류 CRUD ──
    btnTcAdd.addEventListener('click', () => {
        tcForm.reset();
        tcForm.querySelector('[name="id"]').value = '';
        tcForm.querySelector('[name="is_active"]').checked = true;
        fillAppliesCheckboxes(tcForm, '');
        BO.showFormErrors(tcForm, {});
        setMode(tcModal, 'create');
        open(tcModal);
    });

    btnTcEdit.addEventListener('click', () => {
        if (!currentCat) return;
        tcForm.querySelector('[name="id"]').value = currentCat.id;
        tcForm.querySelector('[name="code"]').value = currentCat.code;
        tcForm.querySelector('[name="code"]').readOnly = !!currentCat.is_system;
        tcForm.querySelector('[name="name"]').value = currentCat.name;
        tcForm.querySelector('[name="sort_order"]').value = currentCat.sort_order;
        tcForm.querySelector('[name="is_active"]').checked = !!currentCat.is_active;
        tcForm.querySelector('[name="description"]').value = currentCat.description || '';
        fillAppliesCheckboxes(tcForm, currentCat.applies_to);
        BO.showFormErrors(tcForm, {});
        setMode(tcModal, 'edit');
        open(tcModal);
    });

    tcForm.addEventListener('submit', async e => {
        e.preventDefault();
        BO.showFormErrors(tcForm, {});
        const fd = new FormData(tcForm);
        const payload = Object.fromEntries(fd.entries());
        payload.is_active = tcForm.querySelector('[name="is_active"]').checked ? 'on' : '';
        payload.applies_to = readAppliesCSV(tcForm);
        const isEdit = tcModal.dataset.mode === 'edit';
        const url = isEdit
            ? `/backoffice/api/threshold-categories/${payload.id}/update/`
            : `/backoffice/api/threshold-categories/create/`;
        const { ok, status, data } = await BO.fetchJSON(url, { method:'POST', body:JSON.stringify(payload) });
        if (!ok) {
            if (status === 400 && data.errors) {
                BO.showFormErrors(tcForm, data.errors);
                BO.toast('입력값을 확인해 주세요.', 'error');
            } else BO.toast(data.error || '저장 실패', 'error');
            return;
        }
        BO.toast(isEdit ? '수정되었습니다.' : '등록되었습니다.', 'success');
        close(tcModal);
        setTimeout(() => location.reload(), 400);
    });

    // ── 임계치 항목 CRUD ──
    btnThAdd.addEventListener('click', () => {
        if (!currentCat) return;
        thForm.reset();
        thForm.querySelector('[name="id"]').value = '';
        thForm.querySelector('[name="category_id"]').value = currentCat.id;
        thForm.querySelector('[name="is_active"]').checked = true;
        fillAppliesCheckboxes(thForm, currentCat.applies_to || 'realtime,alarm');
        BO.showFormErrors(thForm, {});
        setMode(thModal, 'create');
        open(thModal);
    });

    thBody.addEventListener('click', async e => {
        const btn = e.target.closest('[data-edit]');
        if (!btn) return;
        const id = parseInt(btn.dataset.edit, 10);
        const t = currentItems.find(x => x.id === id);
        if (!t) return;
        thForm.querySelector('[name="id"]').value = t.id;
        thForm.querySelector('[name="category_id"]').value = currentCat.id;
        thForm.querySelector('[name="item_code"]').value = t.item_code;
        thForm.querySelector('[name="item_name"]').value = t.item_name;
        thForm.querySelector('[name="unit"]').value = t.unit;
        thForm.querySelector('[name="operator"]').value = t.operator;
        thForm.querySelector('[name="caution_value"]').value = t.caution_value;
        thForm.querySelector('[name="danger_value"]').value = t.danger_value;
        thForm.querySelector('[name="is_active"]').checked = !!t.is_active;
        thForm.querySelector('[name="description"]').value = t.description || '';
        fillAppliesCheckboxes(thForm, t.applies_to);
        BO.showFormErrors(thForm, {});
        setMode(thModal, 'edit');
        open(thModal);
    });

    thForm.addEventListener('submit', async e => {
        e.preventDefault();
        BO.showFormErrors(thForm, {});
        const fd = new FormData(thForm);
        const payload = Object.fromEntries(fd.entries());
        payload.is_active = thForm.querySelector('[name="is_active"]').checked ? 'on' : '';
        payload.applies_to = readAppliesCSV(thForm);
        const isEdit = thModal.dataset.mode === 'edit';
        const url = isEdit
            ? `/backoffice/api/thresholds/${payload.id}/update/`
            : `/backoffice/api/thresholds/create/`;
        const { ok, status, data } = await BO.fetchJSON(url, { method:'POST', body:JSON.stringify(payload) });
        if (!ok) {
            if (status === 400 && data.errors) {
                BO.showFormErrors(thForm, data.errors);
                BO.toast('입력값을 확인해 주세요.', 'error');
            } else BO.toast(data.error || '저장 실패', 'error');
            return;
        }
        BO.toast(isEdit ? '수정되었습니다.' : '등록되었습니다.', 'success');
        close(thModal);
        await loadCat(currentCat.id);
    });

    async function bulkRun(url, body, msg) {
        const res = await BO.fetchJSON(url, { method:'POST', body: JSON.stringify(body) });
        if (!res.ok) { BO.toast(res.data.error || '실패', 'error'); return; }
        BO.toast(msg, 'success');
        await loadCat(currentCat.id);
    }
    btnThDel.addEventListener('click', async () => {
        const ids = selectedIds();
        if (!ids.length) return;
        if (!await BO.confirm(`선택한 ${ids.length}건을 삭제하시겠습니까?`)) return;
        bulkRun('/backoffice/api/thresholds/bulk-delete/', { ids }, '삭제되었습니다.');
    });
    btnThOff.addEventListener('click', () => {
        const ids = selectedIds();
        if (!ids.length) return;
        bulkRun('/backoffice/api/thresholds/bulk-toggle/', { ids, is_active: false }, '미사용 처리되었습니다.');
    });
    btnThOn.addEventListener('click', () => {
        const ids = selectedIds();
        if (!ids.length) return;
        bulkRun('/backoffice/api/thresholds/bulk-toggle/', { ids, is_active: true }, '사용 처리되었습니다.');
    });

    function escapeHtml(s) {
        if (s == null) return '';
        return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;').replace(/'/g,'&#39;');
    }

    const first = treeEl.querySelector('li[data-tc-id]');
    if (first) first.click();
})();
