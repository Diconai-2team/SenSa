/* ============================================================
   백오피스 — 사용자 관리 JS
   ----------------------------------------------------------------
   기능:
     - 사용자 등록 모달 (open/close + submit + validation 표시)
     - 사용자 수정 모달 (행의 [수정] 버튼 → AJAX 로 상세 fetch → 모달 prefill)
     - 일괄 액션 (삭제/잠금/잠금해제) — 체크박스 선택 → 활성화
     - 전체 선택 체크박스
     - 정렬 변경 시 GET 으로 재조회
   ============================================================ */
(function () {
    'use strict';

    // ───────────────────── DOM refs ─────────────────────
    const modal     = document.getElementById('bo-user-modal');
    const form      = document.getElementById('bo-user-form');
    const tableBody = document.querySelector('#bo-user-table tbody');
    const checkAll  = document.getElementById('bo-check-all');
    const sortSel   = document.getElementById('bo-sort');
    const btnDel    = document.getElementById('bo-bulk-delete');
    const btnLock   = document.getElementById('bo-bulk-lock');
    const btnUnlock = document.getElementById('bo-bulk-unlock');

    // ───────────────────── 모달 모드 토글 ─────────────────────
    function setModalMode(mode) {
        modal.dataset.mode = mode;  // 'create' | 'edit'
        // [data-create-only] / [data-edit-only] 토글
        modal.querySelectorAll('[data-create-only]').forEach(el => {
            el.style.display = (mode === 'create') ? '' : 'none';
        });
        modal.querySelectorAll('[data-edit-only]').forEach(el => {
            el.style.display = (mode === 'edit') ? '' : 'none';
        });
    }

    function openModal(mode) {
        setModalMode(mode);
        modal.classList.add('is-open');
        document.body.style.overflow = 'hidden';
    }

    function closeModal() {
        modal.classList.remove('is-open');
        document.body.style.overflow = '';
        form.reset();
        BO.showFormErrors(form, {});  // 에러 클리어
        form.querySelector('[name="id"]').value = '';
    }

    // ───────────────────── [등록] 버튼 ─────────────────────
    document.querySelector('[data-open-create-modal]').addEventListener('click', () => {
        openModal('create');
    });

    // ───────────────────── 모달 닫기 ─────────────────────
    modal.addEventListener('click', (e) => {
        if (e.target === modal || e.target.matches('[data-close-modal]')) {
            closeModal();
        }
    });
    document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape' && modal.classList.contains('is-open')) closeModal();
    });

    // ───────────────────── [수정] 버튼 (테이블 행) ─────────────────────
    tableBody.addEventListener('click', async (e) => {
        const editBtn = e.target.closest('[data-edit-user]');
        if (!editBtn) return;

        const userId = editBtn.dataset.editUser;
        const { ok, data } = await BO.fetchJSON(`/backoffice/api/users/${userId}/`);
        if (!ok) {
            BO.toast('사용자 정보를 불러오지 못했습니다.', 'error');
            return;
        }
        const u = data.user;

        // prefill
        form.querySelector('[name="id"]').value             = u.id;
        form.querySelector('[name="name"]').value           = u.name || '';
        form.querySelector('[name="username"]').value       = u.username;
        form.querySelector('[name="username"]').readOnly    = true;
        form.querySelector('[name="organization"]').value   = u.organization_id || '';
        form.querySelector('[name="role"]').value           = u.role;
        form.querySelector('[name="position_obj"]').value   = u.position_obj_id || '';
        form.querySelector('[name="account_status"]').value = u.account_status;
        form.querySelector('[name="email"]').value          = u.email || '';
        form.querySelector('[name="phone"]').value          = u.phone || '';

        openModal('edit');
    });

    // ───────────────────── 폼 제출 ─────────────────────
    form.addEventListener('submit', async (e) => {
        e.preventDefault();
        BO.showFormErrors(form, {});

        const fd = new FormData(form);
        const payload = Object.fromEntries(fd.entries());

        const isEdit = modal.dataset.mode === 'edit';
        const url = isEdit
            ? `/backoffice/api/users/${payload.id}/update/`
            : '/backoffice/api/users/create/';

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

        BO.toast(isEdit ? '저장되었습니다.' : '등록되었습니다.', 'success');
        closeModal();
        // 목록 새로고침 (필터/정렬/페이지 보존)
        setTimeout(() => location.reload(), 400);
    });

    // ───────────────────── 정렬 변경 ─────────────────────
    sortSel.addEventListener('change', () => {
        const url = new URL(location.href);
        url.searchParams.set('sort', sortSel.value);
        url.searchParams.delete('page');  // 정렬 시 1페이지로
        location.href = url.toString();
    });

    // ───────────────────── 체크박스 / 일괄 액션 ─────────────────────
    function selectedIds() {
        return Array.from(
            tableBody.querySelectorAll('.bo-row-check:checked')
        ).map(c => parseInt(c.value, 10));
    }

    function refreshBulkButtons() {
        const ids = selectedIds();
        const has = ids.length > 0;
        btnDel.disabled = !has;
        btnLock.disabled = !has;
        btnUnlock.disabled = !has;

        // 행 강조
        tableBody.querySelectorAll('tr').forEach(tr => {
            const c = tr.querySelector('.bo-row-check');
            tr.classList.toggle('is-selected', c && c.checked);
        });
    }

    tableBody.addEventListener('change', (e) => {
        if (e.target.classList.contains('bo-row-check')) refreshBulkButtons();
    });

    checkAll.addEventListener('change', () => {
        tableBody.querySelectorAll('.bo-row-check').forEach(c => {
            c.checked = checkAll.checked;
        });
        refreshBulkButtons();
    });

    async function runBulk(url, confirmMsg, successMsg) {
        const ids = selectedIds();
        if (!ids.length) return;
        const ok = await BO.confirm(confirmMsg);
        if (!ok) return;
        const res = await BO.fetchJSON(url, {
            method: 'POST',
            body: JSON.stringify({ ids }),
        });
        if (!res.ok) {
            BO.toast(res.data.error || '실패', 'error');
            return;
        }
        BO.toast(successMsg, 'success');
        setTimeout(() => location.reload(), 400);
    }

    btnDel.addEventListener('click', () => runBulk(
        '/backoffice/api/users/bulk-delete/',
        `선택한 ${selectedIds().length}명을 삭제하시겠습니까?`,
        '삭제되었습니다.',
    ));
    btnLock.addEventListener('click', () => runBulk(
        '/backoffice/api/users/bulk-lock/',
        `선택한 ${selectedIds().length}명을 잠금 처리하시겠습니까?`,
        '잠금 처리되었습니다.',
    ));
    btnUnlock.addEventListener('click', () => runBulk(
        '/backoffice/api/users/bulk-unlock/',
        `선택한 ${selectedIds().length}명의 잠금을 해제하시겠습니까?`,
        '잠금이 해제되었습니다.',
    ));

    // ───────────────────── 초기 상태 ─────────────────────
    refreshBulkButtons();
    setModalMode('create');
})();
