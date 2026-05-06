/* ============================================================
   백오피스 — 공통 코드 관리 JS
   2-panel: 좌측 그룹 트리 → 우측 정보카드 + 코드 목록
   ============================================================ */
(function () {
    'use strict';

    const treeEl    = document.getElementById('bo-cg-tree');
    const emptyCard = document.getElementById('bo-cg-empty');
    const infoCard  = document.getElementById('bo-cg-info-card');
    const codeCard  = document.getElementById('bo-code-card');

    const cgNameEl  = document.getElementById('bo-cg-name');
    const cgCodeEl  = document.getElementById('bo-cg-code');
    const cgCountEl = document.getElementById('bo-cg-count');
    const cgUpdEl   = document.getElementById('bo-cg-updated');
    const cgActiveEl= document.getElementById('bo-cg-active');
    const cgDescEl  = document.getElementById('bo-cg-desc');

    const codeBody  = document.getElementById('bo-code-body');
    const codeCheckAll = document.getElementById('bo-code-check-all');
    const codeCountEl  = document.getElementById('bo-code-count');
    const btnCodeAdd   = document.getElementById('bo-code-add');
    const btnCodeOff   = document.getElementById('bo-code-toggle-off');
    const btnCodeOn    = document.getElementById('bo-code-toggle-on');
    const btnCodeDel   = document.getElementById('bo-code-bulk-delete');

    const cgSearch  = document.getElementById('bo-cg-search');
    const btnCgAdd  = document.getElementById('bo-cg-add');
    const btnCgEdit = document.getElementById('bo-cg-edit');
    const btnCgDel  = document.getElementById('bo-cg-delete');

    const cgModal   = document.getElementById('bo-cg-modal');
    const cgForm    = document.getElementById('bo-cg-form');
    const codeModal = document.getElementById('bo-code-modal');
    const codeForm  = document.getElementById('bo-code-form');

    let currentGroup = null;   // 우측 패널 그룹
    let currentCodes = [];     // 그룹 안 코드 배열

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
    cgSearch.addEventListener('input', () => {
        const q = cgSearch.value.trim().toLowerCase();
        treeEl.querySelectorAll('li[data-cg-id]').forEach(li => {
            const name = (li.dataset.cgName || '').toLowerCase();
            li.style.display = (!q || name.includes(q)) ? '' : 'none';
        });
    });

    // 트리 클릭
    treeEl.addEventListener('click', async e => {
        const li = e.target.closest('li[data-cg-id]');
        if (!li) return;
        const id = parseInt(li.dataset.cgId, 10);
        await loadGroup(id);
        treeEl.querySelectorAll('li').forEach(x => x.classList.remove('is-active'));
        li.classList.add('is-active');
    });

    async function loadGroup(id) {
        const { ok, data } = await BO.fetchJSON(`/backoffice/api/code-groups/${id}/`);
        if (!ok) { BO.toast('그룹을 불러오지 못했습니다.', 'error'); return; }
        currentGroup = data.group;
        currentCodes = data.codes || [];
        renderGroup();
    }

    function renderGroup() {
        emptyCard.style.display = 'none';
        infoCard.style.display = '';
        codeCard.style.display = '';

        cgNameEl.textContent = currentGroup.name;
        cgCodeEl.textContent = currentGroup.code;
        cgCountEl.textContent = `${currentGroup.code_count}건`;
        cgUpdEl.textContent = `${currentGroup.updated_at} (${currentGroup.updated_by_name})`;
        cgActiveEl.innerHTML = currentGroup.is_active
            ? '<span class="bo-badge bo-badge-status-active">사용</span>'
            : '<span class="bo-badge bo-badge-status-disabled">미사용</span>';
        cgDescEl.textContent = currentGroup.description || '';

        // 시스템 그룹은 삭제 불가
        btnCgDel.disabled = !!currentGroup.is_system;
        btnCgDel.title = currentGroup.is_system ? '시스템 그룹은 삭제할 수 없습니다.' : '';

        renderCodes();
    }

    function renderCodes() {
        codeCountEl.textContent = currentCodes.length;
        codeBody.innerHTML = currentCodes.map(c => `
            <tr data-id="${c.id}">
                <td><input type="checkbox" class="bo-checkbox bo-row-check" value="${c.id}"></td>
                <td><code style="font-size:12px;">${escapeHtml(c.code)}</code></td>
                <td>${escapeHtml(c.name)}</td>
                <td>${c.sort_order}</td>
                <td>${c.is_active
                    ? '<span class="bo-badge bo-badge-status-active">사용</span>'
                    : '<span class="bo-badge bo-badge-status-disabled">미사용</span>'}</td>
                <td>${escapeHtml(c.updated_at)}</td>
                <td><button type="button" class="bo-btn bo-btn-sm bo-btn-primary" data-edit="${c.id}">수정</button></td>
            </tr>
        `).join('') || `<tr><td colspan="7" class="bo-table-empty">등록된 코드가 없습니다.</td></tr>`;
        codeCheckAll.checked = false;
        refreshBulk();
    }

    function selectedIds() {
        return Array.from(codeBody.querySelectorAll('.bo-row-check:checked')).map(c => parseInt(c.value, 10));
    }
    function refreshBulk() {
        const has = selectedIds().length > 0;
        btnCodeOff.disabled = !has;
        btnCodeOn.disabled = !has;
        btnCodeDel.disabled = !has;
        codeBody.querySelectorAll('tr').forEach(tr => {
            const c = tr.querySelector('.bo-row-check');
            tr.classList.toggle('is-selected', c && c.checked);
        });
    }
    codeBody.addEventListener('change', e => {
        if (e.target.classList.contains('bo-row-check')) refreshBulk();
    });
    codeCheckAll.addEventListener('change', () => {
        codeBody.querySelectorAll('.bo-row-check').forEach(c => c.checked = codeCheckAll.checked);
        refreshBulk();
    });

    // ── 그룹 CRUD ──
    btnCgAdd.addEventListener('click', () => {
        cgForm.reset();
        cgForm.querySelector('[name="id"]').value = '';
        cgForm.querySelector('[name="is_active"]').checked = true;
        BO.showFormErrors(cgForm, {});
        setMode(cgModal, 'create');
        open(cgModal);
    });

    btnCgEdit.addEventListener('click', () => {
        if (!currentGroup) return;
        cgForm.querySelector('[name="id"]').value = currentGroup.id;
        cgForm.querySelector('[name="code"]').value = currentGroup.code;
        cgForm.querySelector('[name="name"]').value = currentGroup.name;
        cgForm.querySelector('[name="sort_order"]').value = currentGroup.sort_order;
        cgForm.querySelector('[name="is_active"]').checked = !!currentGroup.is_active;
        cgForm.querySelector('[name="description"]').value = currentGroup.description || '';
        // 시스템 그룹은 코드 수정 불가
        cgForm.querySelector('[name="code"]').readOnly = !!currentGroup.is_system;
        BO.showFormErrors(cgForm, {});
        setMode(cgModal, 'edit');
        open(cgModal);
    });

    cgForm.addEventListener('submit', async e => {
        e.preventDefault();
        BO.showFormErrors(cgForm, {});
        const fd = new FormData(cgForm);
        const payload = Object.fromEntries(fd.entries());
        payload.is_active = cgForm.querySelector('[name="is_active"]').checked ? 'on' : '';
        const isEdit = cgModal.dataset.mode === 'edit';
        const url = isEdit
            ? `/backoffice/api/code-groups/${payload.id}/update/`
            : `/backoffice/api/code-groups/create/`;
        const { ok, status, data } = await BO.fetchJSON(url, { method:'POST', body:JSON.stringify(payload) });
        if (!ok) {
            if (status === 400 && data.errors) {
                BO.showFormErrors(cgForm, data.errors);
                BO.toast('입력값을 확인해 주세요.', 'error');
            } else BO.toast(data.error || '저장 실패', 'error');
            return;
        }
        BO.toast(isEdit ? '수정되었습니다.' : '등록되었습니다.', 'success');
        close(cgModal);
        setTimeout(() => location.reload(), 400);
    });

    btnCgDel.addEventListener('click', async () => {
        if (!currentGroup || currentGroup.is_system) return;
        const ok = await BO.confirm(
            `'${currentGroup.name}' 그룹을 삭제하시겠습니까?\n` +
            `그룹에 속한 코드 ${currentGroup.code_count}건도 함께 삭제됩니다.`
        );
        if (!ok) return;
        const res = await BO.fetchJSON(
            `/backoffice/api/code-groups/${currentGroup.id}/delete/`,
            { method:'POST' });
        if (!res.ok) { BO.toast(res.data.error || '삭제 실패', 'error'); return; }
        BO.toast('삭제되었습니다.', 'success');
        setTimeout(() => location.reload(), 400);
    });

    // ── 코드 CRUD ──
    btnCodeAdd.addEventListener('click', () => {
        if (!currentGroup) return;
        codeForm.reset();
        codeForm.querySelector('[name="id"]').value = '';
        codeForm.querySelector('[name="group_id"]').value = currentGroup.id;
        codeForm.querySelector('[name="is_active"]').checked = true;
        BO.showFormErrors(codeForm, {});
        setMode(codeModal, 'create');
        open(codeModal);
    });

    codeBody.addEventListener('click', async e => {
        const btn = e.target.closest('[data-edit]');
        if (!btn) return;
        const id = parseInt(btn.dataset.edit, 10);
        const c = currentCodes.find(x => x.id === id);
        if (!c) return;
        codeForm.querySelector('[name="id"]').value = c.id;
        codeForm.querySelector('[name="group_id"]').value = currentGroup.id;
        codeForm.querySelector('[name="code"]').value = c.code;
        codeForm.querySelector('[name="name"]').value = c.name;
        codeForm.querySelector('[name="sort_order"]').value = c.sort_order;
        codeForm.querySelector('[name="is_active"]').checked = !!c.is_active;
        codeForm.querySelector('[name="description"]').value = c.description || '';
        BO.showFormErrors(codeForm, {});
        setMode(codeModal, 'edit');
        open(codeModal);
    });

    codeForm.addEventListener('submit', async e => {
        e.preventDefault();
        BO.showFormErrors(codeForm, {});
        const fd = new FormData(codeForm);
        const payload = Object.fromEntries(fd.entries());
        payload.is_active = codeForm.querySelector('[name="is_active"]').checked ? 'on' : '';
        const isEdit = codeModal.dataset.mode === 'edit';
        const url = isEdit
            ? `/backoffice/api/codes/${payload.id}/update/`
            : `/backoffice/api/codes/create/`;
        const { ok, status, data } = await BO.fetchJSON(url, { method:'POST', body:JSON.stringify(payload) });
        if (!ok) {
            if (status === 400 && data.errors) {
                BO.showFormErrors(codeForm, data.errors);
                BO.toast('입력값을 확인해 주세요.', 'error');
            } else BO.toast(data.error || '저장 실패', 'error');
            return;
        }
        BO.toast(isEdit ? '수정되었습니다.' : '등록되었습니다.', 'success');
        close(codeModal);
        await loadGroup(currentGroup.id);
    });

    async function bulkRun(url, body, msg) {
        const res = await BO.fetchJSON(url, { method:'POST', body: JSON.stringify(body) });
        if (!res.ok) { BO.toast(res.data.error || '실패', 'error'); return; }
        BO.toast(msg, 'success');
        await loadGroup(currentGroup.id);
    }
    btnCodeDel.addEventListener('click', async () => {
        const ids = selectedIds();
        if (!ids.length) return;
        if (!await BO.confirm(`선택한 ${ids.length}건을 삭제하시겠습니까?`)) return;
        bulkRun('/backoffice/api/codes/bulk-delete/', { ids }, '삭제되었습니다.');
    });
    btnCodeOff.addEventListener('click', () => {
        const ids = selectedIds();
        if (!ids.length) return;
        bulkRun('/backoffice/api/codes/bulk-toggle/', { ids, is_active: false }, '미사용 처리되었습니다.');
    });
    btnCodeOn.addEventListener('click', () => {
        const ids = selectedIds();
        if (!ids.length) return;
        bulkRun('/backoffice/api/codes/bulk-toggle/', { ids, is_active: true }, '사용 처리되었습니다.');
    });

    function escapeHtml(s) {
        if (s == null) return '';
        return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;').replace(/'/g,'&#39;');
    }

    // 첫 그룹 자동 선택
    const first = treeEl.querySelector('li[data-cg-id]');
    if (first) first.click();
})();
