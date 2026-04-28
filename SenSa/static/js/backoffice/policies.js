/* ============================================================
   백오피스 — 알림 정책 관리 JS
   ============================================================ */
(function () {
    'use strict';

    const modal = document.getElementById('bo-policy-modal');
    const form  = document.getElementById('bo-policy-form');
    const tbody = document.querySelector('#bo-policy-table tbody');
    const checkAll = document.getElementById('bo-check-all');
    const btnDel = document.getElementById('bo-bulk-delete');
    const btnOn  = document.getElementById('bo-bulk-on');
    const btnOff = document.getElementById('bo-bulk-off');

    function setMode(mode) {
        modal.dataset.mode = mode;
        modal.querySelectorAll('[data-create-only]').forEach(el => el.style.display = (mode==='create'?'':'none'));
        modal.querySelectorAll('[data-edit-only]').forEach(el => el.style.display = (mode==='edit'?'':'none'));
    }
    function openModal(mode) {
        setMode(mode);
        modal.classList.add('is-open');
        document.body.style.overflow='hidden';
    }
    function closeModal() {
        modal.classList.remove('is-open');
        document.body.style.overflow='';
        form.reset();
        BO.showFormErrors(form, {});
        form.querySelector('[name="id"]').value = '';
    }

    function readChannels() {
        return Array.from(form.querySelectorAll('[name^="channel_"]:checked'))
            .map(cb => cb.value).join(',');
    }
    function fillChannels(csv) {
        const set = new Set((csv || '').split(',').filter(Boolean));
        form.querySelectorAll('[name^="channel_"]').forEach(cb => cb.checked = set.has(cb.value));
    }

    function readRecipients() {
        return Array.from(form.querySelectorAll('[name^="rcpt_"]:checked'))
            .map(cb => cb.value).join(',');
    }
    function fillRecipients(csv) {
        const set = new Set((csv || '').split(',').filter(Boolean));
        form.querySelectorAll('[name^="rcpt_"]').forEach(cb => cb.checked = set.has(cb.value));
    }

    document.querySelector('[data-open-create-modal]').addEventListener('click', () => {
        form.querySelector('[name="is_active"]').checked = true;
        openModal('create');
    });

    modal.addEventListener('click', e => {
        if (e.target === modal || e.target.matches('[data-close-modal]')) closeModal();
    });
    document.addEventListener('keydown', e => {
        if (e.key === 'Escape' && modal.classList.contains('is-open')) closeModal();
    });

    tbody.addEventListener('click', async e => {
        const btn = e.target.closest('[data-edit]');
        if (!btn) return;
        const { ok, data } = await BO.fetchJSON(`/backoffice/api/policies/${btn.dataset.edit}/`);
        if (!ok) { BO.toast('정책을 불러오지 못했습니다.', 'error'); return; }
        const p = data.policy;
        form.querySelector('[name="id"]').value = p.id;
        form.querySelector('[name="code"]').value = p.code;
        form.querySelector('[name="name"]').value = p.name;
        form.querySelector('[name="risk_category"]').value = p.risk_category_id;
        form.querySelector('[name="alarm_level"]').value = p.alarm_level_id;
        form.querySelector('[name="message_template"]').value = p.message_template || '';
        form.querySelector('[name="sort_order"]').value = p.sort_order;
        form.querySelector('[name="is_active"]').checked = !!p.is_active;
        form.querySelector('[name="description"]').value = p.description || '';
        fillChannels(p.channels_csv);
        fillRecipients(p.recipients_csv);
        BO.showFormErrors(form, {});
        openModal('edit');
    });

    form.addEventListener('submit', async e => {
        e.preventDefault();
        BO.showFormErrors(form, {});
        const fd = new FormData(form);
        const payload = Object.fromEntries(fd.entries());
        payload.is_active = form.querySelector('[name="is_active"]').checked ? 'on' : '';
        payload.channels_csv = readChannels();
        payload.recipients_csv = readRecipients();
        const isEdit = modal.dataset.mode === 'edit';
        const url = isEdit
            ? `/backoffice/api/policies/${payload.id}/update/`
            : `/backoffice/api/policies/create/`;
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
        bulk('/backoffice/api/policies/bulk-delete/', { ids }, '삭제되었습니다.');
    });
    btnOn.addEventListener('click', () => {
        const ids = selectedIds();
        if (!ids.length) return;
        bulk('/backoffice/api/policies/bulk-toggle/', { ids, is_active: true }, '사용 처리되었습니다.');
    });
    btnOff.addEventListener('click', () => {
        const ids = selectedIds();
        if (!ids.length) return;
        bulk('/backoffice/api/policies/bulk-toggle/', { ids, is_active: false }, '미사용 처리되었습니다.');
    });

    refresh();
    setMode('create');
})();
