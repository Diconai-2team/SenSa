/* ============================================================
   백오피스 — 직위 관리 JS
   ============================================================ */
(function () {
    'use strict';

    const modal     = document.getElementById('bo-pos-modal');
    const form      = document.getElementById('bo-pos-form');
    const tableBody = document.querySelector('#bo-pos-table tbody');
    const checkAll  = document.getElementById('bo-check-all');
    const btnDel    = document.getElementById('bo-bulk-delete');

    function setMode(mode) {
        modal.dataset.mode = mode;
        modal.querySelectorAll('[data-create-only]').forEach(el => el.style.display = (mode==='create'?'':'none'));
        modal.querySelectorAll('[data-edit-only]').forEach(el => el.style.display = (mode==='edit'?'':'none'));
    }
    function openModal(mode) {
        setMode(mode);
        modal.classList.add('is-open');
        document.body.style.overflow = 'hidden';
    }
    function closeModal() {
        modal.classList.remove('is-open');
        document.body.style.overflow = '';
        form.reset();
        BO.showFormErrors(form, {});
        form.querySelector('[name="id"]').value = '';
        // checkbox 기본값 복원 (등록 시 체크 상태)
        form.querySelector('[name="is_active"]').checked = true;
    }

    document.querySelector('[data-open-create-modal]').addEventListener('click', () => {
        openModal('create');
    });

    modal.addEventListener('click', (e) => {
        if (e.target === modal || e.target.matches('[data-close-modal]')) closeModal();
    });
    document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape' && modal.classList.contains('is-open')) closeModal();
    });

    // [수정] 버튼
    tableBody.addEventListener('click', async (e) => {
        const btn = e.target.closest('[data-edit]');
        if (!btn) return;
        const id = btn.dataset.edit;
        const { ok, data } = await BO.fetchJSON(`/backoffice/api/positions/${id}/`);
        if (!ok) {
            BO.toast('직위 정보를 불러오지 못했습니다.', 'error');
            return;
        }
        const p = data.position;
        form.querySelector('[name="id"]').value = p.id;
        form.querySelector('[name="name"]').value = p.name;
        form.querySelector('[name="sort_order"]').value = p.sort_order;
        form.querySelector('[name="is_active"]').checked = !!p.is_active;
        BO.showFormErrors(form, {});
        openModal('edit');
    });

    // submit
    form.addEventListener('submit', async (e) => {
        e.preventDefault();
        BO.showFormErrors(form, {});
        const fd = new FormData(form);
        const payload = Object.fromEntries(fd.entries());
        // checkbox 처리: 체크 해제 시 'is_active' 키가 빠져있음
        payload.is_active = form.querySelector('[name="is_active"]').checked ? 'on' : '';

        const isEdit = modal.dataset.mode === 'edit';
        const url = isEdit
            ? `/backoffice/api/positions/${payload.id}/update/`
            : '/backoffice/api/positions/create/';

        const { ok, status, data } = await BO.fetchJSON(url, {
            method: 'POST',
            body: JSON.stringify(payload),
        });
        if (!ok) {
            if (status === 400 && data.errors) {
                BO.showFormErrors(form, data.errors);
                BO.toast('입력값을 확인해 주세요.', 'error');
            } else {
                BO.toast(data.error || '저장 실패', 'error');
            }
            return;
        }
        BO.toast(isEdit ? '수정되었습니다.' : '등록되었습니다.', 'success');
        closeModal();
        setTimeout(() => location.reload(), 400);
    });

    // 체크박스 / 일괄 삭제
    function selectedIds() {
        return Array.from(tableBody.querySelectorAll('.bo-row-check:checked')).map(c => parseInt(c.value, 10));
    }
    function refreshBulk() {
        const ids = selectedIds();
        btnDel.disabled = ids.length === 0;
        tableBody.querySelectorAll('tr').forEach(tr => {
            const c = tr.querySelector('.bo-row-check');
            tr.classList.toggle('is-selected', c && c.checked);
        });
    }
    tableBody.addEventListener('change', (e) => {
        if (e.target.classList.contains('bo-row-check')) refreshBulk();
    });
    checkAll.addEventListener('change', () => {
        tableBody.querySelectorAll('.bo-row-check').forEach(c => c.checked = checkAll.checked);
        refreshBulk();
    });
    btnDel.addEventListener('click', async () => {
        const ids = selectedIds();
        if (!ids.length) return;
        const ok = await BO.confirm(`선택한 ${ids.length}건을 삭제하시겠습니까?`);
        if (!ok) return;
        const res = await BO.fetchJSON('/backoffice/api/positions/bulk-delete/', {
            method: 'POST',
            body: JSON.stringify({ ids }),
        });
        if (!res.ok) {
            BO.toast(res.data.error || '삭제 실패', 'error');
            return;
        }
        BO.toast('삭제되었습니다.', 'success');
        setTimeout(() => location.reload(), 400);
    });

    refreshBulk();
    setMode('create');
})();
