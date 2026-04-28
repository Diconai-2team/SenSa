/* 백오피스 — 공지사항 관리 */
(function () {
    'use strict';
    const modal = document.getElementById('bo-notice-modal');
    const form  = document.getElementById('bo-notice-form');
    const tbody = document.querySelector('#bo-notice-table tbody');
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
        form.reset(); BO.showFormErrors(form, {});
        form.querySelector('[name="id"]').value='';
    }

    document.querySelector('[data-open-create-modal]').addEventListener('click', () => {
        form.querySelector('[name="is_published"]').checked = true;
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
        const { ok, data } = await BO.fetchJSON(`/backoffice/api/notices/${btn.dataset.edit}/`);
        if (!ok) { BO.toast('공지를 불러오지 못했습니다.', 'error'); return; }
        const n = data.notice;
        form.querySelector('[name="id"]').value = n.id;
        form.querySelector('[name="title"]').value = n.title;
        form.querySelector('[name="category"]').value = n.category;
        form.querySelector('[name="content"]').value = n.content;
        form.querySelector('[name="is_pinned"]').checked = !!n.is_pinned;
        form.querySelector('[name="is_published"]').checked = !!n.is_published;
        form.querySelector('[name="published_from"]').value = n.published_from || '';
        form.querySelector('[name="published_to"]').value = n.published_to || '';
        BO.showFormErrors(form, {});
        open('edit');
    });

    form.addEventListener('submit', async e => {
        e.preventDefault();
        BO.showFormErrors(form, {});
        const fd = new FormData(form);
        const payload = Object.fromEntries(fd.entries());
        payload.is_pinned = form.querySelector('[name="is_pinned"]').checked ? 'on' : '';
        payload.is_published = form.querySelector('[name="is_published"]').checked ? 'on' : '';
        // v5 — 등록 시 발송 옵션
        const sendNotifyCb = form.querySelector('[name="send_notify"]');
        if (sendNotifyCb) payload.send_notify = sendNotifyCb.checked;
        const isEdit = modal.dataset.mode === 'edit';
        const url = isEdit
            ? `/backoffice/api/notices/${payload.id}/update/`
            : `/backoffice/api/notices/create/`;
        const { ok, status, data } = await BO.fetchJSON(url, { method:'POST', body:JSON.stringify(payload) });
        if (!ok) {
            if (status === 400 && data.errors) {
                BO.showFormErrors(form, data.errors);
                BO.toast('입력값을 확인해 주세요.', 'error');
            } else BO.toast(data.error || '저장 실패', 'error');
            return;
        }
        let msg = isEdit ? '수정되었습니다.' : '등록되었습니다.';
        if (data.dispatched) msg += ` (${data.dispatched}건 알림 발송)`;
        BO.toast(msg, 'success');
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
        bulk('/backoffice/api/notices/bulk-delete/', { ids }, '삭제되었습니다.');
    });
    btnOn.addEventListener('click', () => {
        const ids = selectedIds();
        if (!ids.length) return;
        bulk('/backoffice/api/notices/bulk-toggle/', { ids, is_published: true }, '게시 처리되었습니다.');
    });
    btnOff.addEventListener('click', () => {
        const ids = selectedIds();
        if (!ids.length) return;
        bulk('/backoffice/api/notices/bulk-toggle/', { ids, is_published: false }, '게시 중지 처리되었습니다.');
    });

    refresh();
    setMode('create');
})();
