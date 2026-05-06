/* ============================================================
   백오피스 — 위험 기준 (알람 단계) JS
   ============================================================ */
(function () {
    'use strict';

    const modal = document.getElementById('bo-al-modal');
    const form  = document.getElementById('bo-al-form');
    const tbody = document.querySelector('#bo-al-table tbody');
    const checkAll = document.getElementById('bo-al-check-all');
    const btnDel = document.getElementById('bo-al-bulk-delete');
    const btnAdd = document.getElementById('bo-al-add');

    function setMode(mode) {
        modal.dataset.mode = mode;
        modal.querySelectorAll('[data-create-only]').forEach(el => el.style.display = (mode==='create'?'':'none'));
        modal.querySelectorAll('[data-edit-only]').forEach(el => el.style.display = (mode==='edit'?'':'none'));
    }
    function open() { modal.classList.add('is-open'); document.body.style.overflow='hidden'; }
    function close() {
        modal.classList.remove('is-open');
        document.body.style.overflow='';
        form.reset();
        BO.showFormErrors(form, {});
        form.querySelector('[name="id"]').value = '';
        form.querySelector('[name="is_active"]').checked = true;
        form.querySelector('[name="code"]').readOnly = false;
    }

    btnAdd.addEventListener('click', () => {
        form.querySelector('[name="is_active"]').checked = true;
        setMode('create');
        open();
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
        const id = btn.dataset.edit;
        const { ok, data } = await BO.fetchJSON(`/backoffice/api/alarm-levels/${id}/`);
        if (!ok) { BO.toast('정보를 불러오지 못했습니다.', 'error'); return; }
        const a = data.alarm_level;
        form.querySelector('[name="id"]').value = a.id;
        form.querySelector('[name="code"]').value = a.code;
        form.querySelector('[name="code"]').readOnly = !!a.is_system;
        form.querySelector('[name="name"]').value = a.name;
        form.querySelector('[name="color"]').value = a.color;
        form.querySelector('[name="intensity"]').value = a.intensity;
        form.querySelector('[name="priority"]').value = a.priority;
        form.querySelector('[name="is_active"]').checked = !!a.is_active;
        form.querySelector('[name="description"]').value = a.description || '';
        BO.showFormErrors(form, {});
        setMode('edit');
        open();
    });

    form.addEventListener('submit', async e => {
        e.preventDefault();
        BO.showFormErrors(form, {});
        const fd = new FormData(form);
        const payload = Object.fromEntries(fd.entries());
        payload.is_active = form.querySelector('[name="is_active"]').checked ? 'on' : '';
        const isEdit = modal.dataset.mode === 'edit';
        const url = isEdit
            ? `/backoffice/api/alarm-levels/${payload.id}/update/`
            : `/backoffice/api/alarm-levels/create/`;
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
        btnDel.disabled = selectedIds().length === 0;
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
    btnDel.addEventListener('click', async () => {
        const ids = selectedIds();
        if (!ids.length) return;
        if (!await BO.confirm(`선택한 ${ids.length}건을 삭제하시겠습니까?`)) return;
        const res = await BO.fetchJSON('/backoffice/api/alarm-levels/bulk-delete/', {
            method:'POST', body: JSON.stringify({ ids }),
        });
        if (!res.ok) { BO.toast(res.data.error || '실패', 'error'); return; }
        BO.toast('삭제되었습니다.', 'success');
        setTimeout(() => location.reload(), 400);
    });

    refresh();
    setMode('create');
})();
