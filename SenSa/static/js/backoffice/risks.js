/* ============================================================
   백오피스 — 위험 유형 관리 JS
   2-panel: 좌측 분류 트리 → 우측 정보카드 + 위험 유형 목록
   ============================================================ */
(function () {
    'use strict';

    const treeEl    = document.getElementById('bo-rc-tree');
    const emptyCard = document.getElementById('bo-rc-empty');
    const infoCard  = document.getElementById('bo-rc-info-card');
    const rtCard    = document.getElementById('bo-rt-card');

    const rcNameEl  = document.getElementById('bo-rc-name');
    const rcCodeEl  = document.getElementById('bo-rc-code');
    const rcCountEl = document.getElementById('bo-rc-count');
    const rcAppEl   = document.getElementById('bo-rc-applies');
    const rcActiveEl= document.getElementById('bo-rc-active');
    const rcDescEl  = document.getElementById('bo-rc-desc');

    const rtBody    = document.getElementById('bo-rt-body');
    const rtCheckAll= document.getElementById('bo-rt-check-all');
    const rtCountEl = document.getElementById('bo-rt-count');

    const rcSearch  = document.getElementById('bo-rc-search');
    const btnRcAdd  = document.getElementById('bo-rc-add');
    const btnRcEdit = document.getElementById('bo-rc-edit');
    const btnRcDel  = document.getElementById('bo-rc-delete');
    const btnRtAdd  = document.getElementById('bo-rt-add');
    const btnRtDel  = document.getElementById('bo-rt-bulk-delete');

    const rcModal   = document.getElementById('bo-rc-modal');
    const rcForm    = document.getElementById('bo-rc-form');
    const rtModal   = document.getElementById('bo-rt-modal');
    const rtForm    = document.getElementById('bo-rt-form');

    let currentCat   = null;
    let currentTypes = [];

    const APPLIES_LABELS = {
        realtime: '실시간 관제',
        event:    '이벤트 이력',
        alarm:    '알림',
    };

    // 모달 헬퍼
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

    // 트리 검색
    rcSearch.addEventListener('input', () => {
        const q = rcSearch.value.trim().toLowerCase();
        treeEl.querySelectorAll('li[data-rc-id]').forEach(li => {
            const name = (li.dataset.rcName || '').toLowerCase();
            li.style.display = (!q || name.includes(q)) ? '' : 'none';
        });
    });

    // 트리 클릭
    treeEl.addEventListener('click', async e => {
        const li = e.target.closest('li[data-rc-id]');
        if (!li) return;
        const id = parseInt(li.dataset.rcId, 10);
        await loadCat(id);
        treeEl.querySelectorAll('li').forEach(x => x.classList.remove('is-active'));
        li.classList.add('is-active');
    });

    async function loadCat(id) {
        const { ok, data } = await BO.fetchJSON(`/backoffice/api/risk-categories/${id}/`);
        if (!ok) { BO.toast('분류 정보를 불러오지 못했습니다.', 'error'); return; }
        currentCat = data.category;
        currentTypes = data.types || [];
        renderCat();
    }

    function renderCat() {
        emptyCard.style.display = 'none';
        infoCard.style.display = '';
        rtCard.style.display = '';

        rcNameEl.textContent = currentCat.name;
        rcCodeEl.textContent = currentCat.code;
        rcCountEl.textContent = `${currentCat.type_count}건`;
        rcActiveEl.innerHTML = currentCat.is_active
            ? '<span class="bo-badge bo-badge-status-active">사용</span>'
            : '<span class="bo-badge bo-badge-status-disabled">미사용</span>';
        rcDescEl.textContent = currentCat.description || '';

        const pills = (currentCat.applies_to_list || []).map(
            k => `<span class="bo-pill">${APPLIES_LABELS[k] || k}</span>`
        ).join('');
        rcAppEl.innerHTML = pills
            ? `<div class="bo-applies-pills">${pills}</div>`
            : '<span class="bo-text-subtle">미지정</span>';

        btnRcDel.disabled = !!currentCat.is_system;
        btnRcDel.title = currentCat.is_system ? '시스템 분류는 삭제할 수 없습니다.' : '';

        renderTypes();
    }

    function renderTypes() {
        rtCountEl.textContent = currentTypes.length;
        rtBody.innerHTML = currentTypes.map(t => `
            <tr data-id="${t.id}">
                <td><input type="checkbox" class="bo-checkbox bo-row-check" value="${t.id}"></td>
                <td><code style="font-size:12px;">${escapeHtml(t.code)}</code></td>
                <td>${escapeHtml(t.name)}</td>
                <td>${t.show_on_map ? '✓' : '–'}</td>
                <td>${t.is_active
                    ? '<span class="bo-badge bo-badge-status-active">사용</span>'
                    : '<span class="bo-badge bo-badge-status-disabled">미사용</span>'}</td>
                <td><button type="button" class="bo-btn bo-btn-sm bo-btn-primary" data-edit="${t.id}">수정</button></td>
            </tr>
        `).join('') || `<tr><td colspan="6" class="bo-table-empty">등록된 위험 유형이 없습니다.</td></tr>`;
        rtCheckAll.checked = false;
        refreshBulk();
    }

    function selectedIds() {
        return Array.from(rtBody.querySelectorAll('.bo-row-check:checked')).map(c => parseInt(c.value, 10));
    }
    function refreshBulk() {
        btnRtDel.disabled = selectedIds().length === 0;
        rtBody.querySelectorAll('tr').forEach(tr => {
            const c = tr.querySelector('.bo-row-check');
            tr.classList.toggle('is-selected', c && c.checked);
        });
    }
    rtBody.addEventListener('change', e => {
        if (e.target.classList.contains('bo-row-check')) refreshBulk();
    });
    rtCheckAll.addEventListener('change', () => {
        rtBody.querySelectorAll('.bo-row-check').forEach(c => c.checked = rtCheckAll.checked);
        refreshBulk();
    });

    // ── 분류 CRUD ──
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

    btnRcAdd.addEventListener('click', () => {
        rcForm.reset();
        rcForm.querySelector('[name="id"]').value = '';
        rcForm.querySelector('[name="is_active"]').checked = true;
        fillAppliesCheckboxes(rcForm, '');
        BO.showFormErrors(rcForm, {});
        setMode(rcModal, 'create');
        open(rcModal);
    });

    btnRcEdit.addEventListener('click', () => {
        if (!currentCat) return;
        rcForm.querySelector('[name="id"]').value = currentCat.id;
        rcForm.querySelector('[name="code"]').value = currentCat.code;
        rcForm.querySelector('[name="name"]').value = currentCat.name;
        rcForm.querySelector('[name="sort_order"]').value = currentCat.sort_order;
        rcForm.querySelector('[name="is_active"]').checked = !!currentCat.is_active;
        rcForm.querySelector('[name="description"]').value = currentCat.description || '';
        rcForm.querySelector('[name="code"]').readOnly = !!currentCat.is_system;
        fillAppliesCheckboxes(rcForm, currentCat.applies_to);
        BO.showFormErrors(rcForm, {});
        setMode(rcModal, 'edit');
        open(rcModal);
    });

    rcForm.addEventListener('submit', async e => {
        e.preventDefault();
        BO.showFormErrors(rcForm, {});
        const fd = new FormData(rcForm);
        const payload = Object.fromEntries(fd.entries());
        payload.is_active = rcForm.querySelector('[name="is_active"]').checked ? 'on' : '';
        payload.applies_to = readAppliesCSV(rcForm);
        const isEdit = rcModal.dataset.mode === 'edit';
        const url = isEdit
            ? `/backoffice/api/risk-categories/${payload.id}/update/`
            : `/backoffice/api/risk-categories/create/`;
        const { ok, status, data } = await BO.fetchJSON(url, { method:'POST', body:JSON.stringify(payload) });
        if (!ok) {
            if (status === 400 && data.errors) {
                BO.showFormErrors(rcForm, data.errors);
                BO.toast('입력값을 확인해 주세요.', 'error');
            } else BO.toast(data.error || '저장 실패', 'error');
            return;
        }
        BO.toast(isEdit ? '수정되었습니다.' : '등록되었습니다.', 'success');
        close(rcModal);
        setTimeout(() => location.reload(), 400);
    });

    btnRcDel.addEventListener('click', async () => {
        if (!currentCat || currentCat.is_system) return;
        const ok = await BO.confirm(
            `'${currentCat.name}' 분류를 삭제하시겠습니까?\n` +
            `유형 ${currentCat.type_count}건도 함께 삭제됩니다.`
        );
        if (!ok) return;
        const res = await BO.fetchJSON(
            `/backoffice/api/risk-categories/${currentCat.id}/delete/`,
            { method:'POST' });
        if (!res.ok) { BO.toast(res.data.error || '삭제 실패', 'error'); return; }
        BO.toast('삭제되었습니다.', 'success');
        setTimeout(() => location.reload(), 400);
    });

    // ── 유형 CRUD ──
    btnRtAdd.addEventListener('click', () => {
        if (!currentCat) return;
        rtForm.reset();
        rtForm.querySelector('[name="id"]').value = '';
        rtForm.querySelector('[name="category_id"]').value = currentCat.id;
        rtForm.querySelector('[name="show_on_map"]').checked = true;
        rtForm.querySelector('[name="is_active"]').checked = true;
        BO.showFormErrors(rtForm, {});
        setMode(rtModal, 'create');
        open(rtModal);
    });

    rtBody.addEventListener('click', async e => {
        const btn = e.target.closest('[data-edit]');
        if (!btn) return;
        const id = parseInt(btn.dataset.edit, 10);
        const t = currentTypes.find(x => x.id === id);
        if (!t) return;
        rtForm.querySelector('[name="id"]').value = t.id;
        rtForm.querySelector('[name="category_id"]').value = currentCat.id;
        rtForm.querySelector('[name="code"]').value = t.code;
        rtForm.querySelector('[name="name"]').value = t.name;
        rtForm.querySelector('[name="sort_order"]').value = t.sort_order;
        rtForm.querySelector('[name="show_on_map"]').checked = !!t.show_on_map;
        rtForm.querySelector('[name="is_active"]').checked = !!t.is_active;
        rtForm.querySelector('[name="description"]').value = t.description || '';
        BO.showFormErrors(rtForm, {});
        setMode(rtModal, 'edit');
        open(rtModal);
    });

    rtForm.addEventListener('submit', async e => {
        e.preventDefault();
        BO.showFormErrors(rtForm, {});
        const fd = new FormData(rtForm);
        const payload = Object.fromEntries(fd.entries());
        payload.show_on_map = rtForm.querySelector('[name="show_on_map"]').checked ? 'on' : '';
        payload.is_active   = rtForm.querySelector('[name="is_active"]').checked ? 'on' : '';
        const isEdit = rtModal.dataset.mode === 'edit';
        const url = isEdit
            ? `/backoffice/api/risk-types/${payload.id}/update/`
            : `/backoffice/api/risk-types/create/`;
        const { ok, status, data } = await BO.fetchJSON(url, { method:'POST', body:JSON.stringify(payload) });
        if (!ok) {
            if (status === 400 && data.errors) {
                BO.showFormErrors(rtForm, data.errors);
                BO.toast('입력값을 확인해 주세요.', 'error');
            } else BO.toast(data.error || '저장 실패', 'error');
            return;
        }
        BO.toast(isEdit ? '수정되었습니다.' : '등록되었습니다.', 'success');
        close(rtModal);
        await loadCat(currentCat.id);
    });

    btnRtDel.addEventListener('click', async () => {
        const ids = selectedIds();
        if (!ids.length) return;
        if (!await BO.confirm(`선택한 ${ids.length}건을 삭제하시겠습니까?`)) return;
        const res = await BO.fetchJSON('/backoffice/api/risk-types/bulk-delete/', {
            method:'POST', body: JSON.stringify({ ids }),
        });
        if (!res.ok) { BO.toast(res.data.error || '실패', 'error'); return; }
        BO.toast('삭제되었습니다.', 'success');
        await loadCat(currentCat.id);
    });

    function escapeHtml(s) {
        if (s == null) return '';
        return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;').replace(/'/g,'&#39;');
    }

    // 첫 분류 자동 선택
    const first = treeEl.querySelector('li[data-rc-id]');
    if (first) first.click();
})();
