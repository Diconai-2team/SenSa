/* ============================================================
   백오피스 — 조직 관리 JS
   ----------------------------------------------------------------
   기능:
     - 조직 트리 클릭 → 우측 부서 정보 + 구성원 카드 갱신
     - 부서 추가/수정/삭제 (모달)
     - 구성원 선택 3-패널 팝업 (조직 목록 / 구성원 목록 / 선택된 구성원)
     - 부서 이동 팝업 (단일 회사 트리 안에서 다른 부서로 이동)
     - 소속 제외, 조직장 임명
   ============================================================ */
(function () {
    'use strict';

    const BOOT = window.BO_ORG_BOOTSTRAP || { company: null, departments: [] };

    // ───────────────────── DOM refs ─────────────────────
    const treeEl     = document.getElementById('bo-org-tree');
    const detailEmpty= document.getElementById('bo-org-detail-empty');
    const infoCard   = document.getElementById('bo-org-info-card');
    const membersCard= document.getElementById('bo-org-members-card');
    const orgNameEl  = document.getElementById('bo-org-name');
    const orgCodeEl  = document.getElementById('bo-org-code');
    const orgMemberCountEl = document.getElementById('bo-org-member-count');
    const orgLeaderEl= document.getElementById('bo-org-leader');
    const orgUpdatedEl= document.getElementById('bo-org-updated');

    const membersBody     = document.getElementById('bo-members-body');
    const membersCheckAll = document.getElementById('bo-members-check-all');
    const membersSelectedEl= document.getElementById('bo-members-selected');
    const btnMove   = document.getElementById('bo-member-move');
    const btnRemove = document.getElementById('bo-member-remove');
    const btnLeader = document.getElementById('bo-member-leader');

    const btnAddDept = document.getElementById('bo-add-dept');
    const btnEditDept= document.getElementById('bo-org-edit');
    const btnDelDept = document.getElementById('bo-org-delete');
    const btnAddMember= document.getElementById('bo-add-member');

    const orgModal   = document.getElementById('bo-org-modal');
    const orgForm    = document.getElementById('bo-org-form');
    const pickerModal= document.getElementById('bo-member-picker');
    const moveModal  = document.getElementById('bo-move-modal');

    const treeSearch = document.getElementById('bo-tree-search');

    // ───────────────────── 상태 ─────────────────────
    let currentOrgId = null;     // 우측 패널이 보고 있는 부서 ID
    let currentOrg   = null;     // 그 부서의 풀 detail (API 응답)
    let currentMembers = [];     // 구성원 배열

    // ───────────────────── 모달 헬퍼 ─────────────────────
    function openModal(modal) {
        modal.classList.add('is-open');
        document.body.style.overflow = 'hidden';
    }
    function closeModal(modal) {
        modal.classList.remove('is-open');
        document.body.style.overflow = '';
    }
    function setOrgModalMode(mode) {
        orgModal.dataset.mode = mode;
        orgModal.querySelectorAll('[data-create-only]').forEach(el => el.style.display = (mode==='create'?'':'none'));
        orgModal.querySelectorAll('[data-edit-only]').forEach(el => el.style.display = (mode==='edit'?'':'none'));
    }

    // 모든 모달 백드롭 클릭/Esc 닫기
    document.querySelectorAll('.bo-modal-backdrop').forEach(m => {
        m.addEventListener('click', (e) => {
            if (e.target === m || e.target.matches('[data-close-modal]')) closeModal(m);
        });
    });
    document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape') {
            document.querySelectorAll('.bo-modal-backdrop.is-open').forEach(closeModal);
        }
    });

    // ───────────────────── 트리 검색 ─────────────────────
    treeSearch.addEventListener('input', () => {
        const q = treeSearch.value.trim().toLowerCase();
        treeEl.querySelectorAll('.bo-org-tree-item').forEach(li => {
            const name = (li.dataset.orgName || '').toLowerCase();
            li.style.display = (!q || name.includes(q)) ? '' : 'none';
        });
    });

    // ───────────────────── 트리 클릭 → 우측 갱신 ─────────────────────
    treeEl.addEventListener('click', async (e) => {
        const li = e.target.closest('.bo-org-tree-item');
        if (!li) return;
        const orgId = parseInt(li.dataset.orgId, 10);
        await loadOrgDetail(orgId);

        treeEl.querySelectorAll('.bo-org-tree-item').forEach(x => x.classList.remove('is-active'));
        li.classList.add('is-active');
    });

    async function loadOrgDetail(orgId) {
        const { ok, data } = await BO.fetchJSON(`/backoffice/api/organizations/${orgId}/`);
        if (!ok) {
            BO.toast('조직 정보를 불러오지 못했습니다.', 'error');
            return;
        }
        currentOrgId = orgId;
        currentOrg = data.organization;
        currentMembers = data.members || [];
        renderOrgDetail();
    }

    function renderOrgDetail() {
        detailEmpty.style.display = 'none';
        infoCard.style.display = '';
        membersCard.style.display = '';

        orgNameEl.textContent = currentOrg.name;
        orgCodeEl.textContent = currentOrg.code || '-';
        orgMemberCountEl.textContent = currentOrg.member_count + '명';
        orgLeaderEl.textContent = currentOrg.leader_name || '-';
        orgUpdatedEl.textContent = `${currentOrg.updated_at} (${currentOrg.updated_by_name})`;

        // '조직 없음' 버킷은 수정/삭제 불가
        btnEditDept.disabled = !!currentOrg.is_unassigned_bucket;
        btnDelDept.disabled  = !!currentOrg.is_unassigned_bucket;

        renderMembers();
    }

    function renderMembers() {
        membersBody.innerHTML = currentMembers.map(m => `
            <tr data-uid="${m.id}">
                <td><input type="checkbox" class="bo-checkbox bo-member-check" value="${m.id}"></td>
                <td>${escapeHtml(m.name || '-')}${m.is_leader ? ' <span class="bo-badge bo-badge-role-admin">조직장</span>' : ''}</td>
                <td>${escapeHtml(m.username)}</td>
                <td>${escapeHtml(m.position || '-')}</td>
                <td>${renderStatusBadge(m.account_status)}</td>
            </tr>
        `).join('') || `<tr><td colspan="5" class="bo-table-empty">소속된 구성원이 없습니다.</td></tr>`;

        membersCheckAll.checked = false;
        refreshMemberButtons();
    }

    function refreshMemberButtons() {
        const ids = selectedMemberIds();
        const has = ids.length > 0;
        btnMove.disabled = !has;
        btnRemove.disabled = !has || currentOrg?.is_unassigned_bucket; // 조직없음 버킷에선 의미 없음
        btnLeader.disabled = ids.length !== 1 || currentOrg?.is_unassigned_bucket; // 단건만
        membersSelectedEl.textContent = `${ids.length}명 선택`;

        membersBody.querySelectorAll('tr[data-uid]').forEach(tr => {
            const c = tr.querySelector('.bo-member-check');
            tr.classList.toggle('is-selected', c && c.checked);
        });
    }

    membersBody.addEventListener('change', (e) => {
        if (e.target.classList.contains('bo-member-check')) refreshMemberButtons();
    });
    membersCheckAll.addEventListener('change', () => {
        membersBody.querySelectorAll('.bo-member-check').forEach(c => c.checked = membersCheckAll.checked);
        refreshMemberButtons();
    });

    function selectedMemberIds() {
        return Array.from(membersBody.querySelectorAll('.bo-member-check:checked'))
            .map(c => parseInt(c.value, 10));
    }

    // ───────────────────── 부서 추가/수정/삭제 ─────────────────────
    btnAddDept.addEventListener('click', () => {
        orgForm.reset();
        orgForm.querySelector('[name="id"]').value = '';
        orgForm.querySelector('[name="parent"]').value = BOOT.company ? BOOT.company.id : '';
        BO.showFormErrors(orgForm, {});
        setOrgModalMode('create');
        openModal(orgModal);
    });

    btnEditDept.addEventListener('click', () => {
        if (!currentOrg) return;
        orgForm.querySelector('[name="id"]').value = currentOrg.id;
        orgForm.querySelector('[name="parent"]').value = currentOrg.parent_id || '';
        orgForm.querySelector('[name="name"]').value = currentOrg.name;
        orgForm.querySelector('[name="code"]').value = currentOrg.code || '';
        orgForm.querySelector('[name="description"]').value = currentOrg.description || '';
        BO.showFormErrors(orgForm, {});
        setOrgModalMode('edit');
        openModal(orgModal);
    });

    orgForm.addEventListener('submit', async (e) => {
        e.preventDefault();
        BO.showFormErrors(orgForm, {});
        const fd = new FormData(orgForm);
        const payload = Object.fromEntries(fd.entries());
        const isEdit = orgModal.dataset.mode === 'edit';
        const url = isEdit
            ? `/backoffice/api/organizations/${payload.id}/update/`
            : '/backoffice/api/organizations/create/';

        const { ok, status, data } = await BO.fetchJSON(url, {
            method: 'POST',
            body: JSON.stringify(payload),
        });
        if (!ok) {
            if (status === 400 && data.errors) {
                BO.showFormErrors(orgForm, data.errors);
                BO.toast('입력값을 확인해 주세요.', 'error');
            } else {
                BO.toast(data.error || '저장 실패', 'error');
            }
            return;
        }
        BO.toast(isEdit ? '수정되었습니다.' : '추가되었습니다.', 'success');
        closeModal(orgModal);
        setTimeout(() => location.reload(), 400);
    });

    btnDelDept.addEventListener('click', async () => {
        if (!currentOrg) return;
        const ok = await BO.confirm(
            `'${currentOrg.name}' 부서를 삭제하시겠습니까?\n` +
            `소속 구성원 ${currentOrg.member_count}명은 '조직 없음' 으로 이동합니다.`
        );
        if (!ok) return;
        const res = await BO.fetchJSON(
            `/backoffice/api/organizations/${currentOrg.id}/delete/`,
            { method: 'POST' },
        );
        if (!res.ok) {
            BO.toast(res.data.error || '삭제 실패', 'error');
            return;
        }
        BO.toast('삭제되었습니다.', 'success');
        setTimeout(() => location.reload(), 400);
    });

    // ───────────────────── 구성원 추가 (3-패널 팝업) ─────────────────────
    let pickerSelectedIds = new Set();
    let pickerSourceUsers = [];     // 현재 패널 가운데 표시되는 후보 구성원

    btnAddMember.addEventListener('click', async () => {
        if (!currentOrg) return;
        pickerSelectedIds = new Set();
        await loadPickerTree();
        await loadPickerSource(null);  // 처음엔 전체
        renderPickerSelected();
        openModal(pickerModal);
    });

    async function loadPickerTree() {
        // 좌측 트리 = boot data 그대로 사용 (조직 없음 포함, 단 "전체" 옵션 추가)
        const wrap = document.getElementById('bo-picker-tree');
        const items = [
            `<li class="bo-org-tree-item is-active" data-pick-org="">전체 구성원</li>`,
            ...BOOT.departments.map(d =>
                `<li class="bo-org-tree-item ${d.is_unassigned ? 'is-unassigned' : ''}" data-pick-org="${d.id}">
                    ${escapeHtml(d.name)} <span class="bo-text-subtle">(${d.member_count})</span>
                </li>`
            ),
        ];
        wrap.innerHTML = items.join('');
        wrap.querySelectorAll('.bo-org-tree-item').forEach(li => {
            li.addEventListener('click', async () => {
                wrap.querySelectorAll('.bo-org-tree-item').forEach(x => x.classList.remove('is-active'));
                li.classList.add('is-active');
                const orgId = li.dataset.pickOrg ? parseInt(li.dataset.pickOrg, 10) : null;
                await loadPickerSource(orgId);
            });
        });
    }

    async function loadPickerSource(orgId) {
        const url = orgId
            ? `/backoffice/api/organizations/member-picker/?org_id=${orgId}`
            : '/backoffice/api/organizations/member-picker/';
        const { ok, data } = await BO.fetchJSON(url);
        if (!ok) {
            BO.toast('구성원 목록을 불러오지 못했습니다.', 'error');
            return;
        }
        pickerSourceUsers = data.users || [];
        renderPickerSource();
    }

    function renderPickerSource() {
        const wrap = document.getElementById('bo-picker-source');
        wrap.innerHTML = pickerSourceUsers.map(u => {
            const checked = pickerSelectedIds.has(u.id) ? 'checked' : '';
            const inCurrent = (u.organization_id === currentOrgId);
            const disabledAttr = inCurrent ? 'disabled' : '';
            const noteHtml = inCurrent
                ? '<span class="bo-text-subtle" style="font-size:11.5px;">이미 소속</span>'
                : `<span class="bo-text-subtle" style="font-size:11.5px;">${escapeHtml(u.organization || '')}</span>`;
            return `
                <label style="display:flex;align-items:center;gap:8px;padding:6px 4px;border-bottom:1px solid var(--bo-border-soft);">
                    <input type="checkbox" class="bo-checkbox bo-picker-check" value="${u.id}" ${checked} ${disabledAttr}>
                    <span style="flex:1;">${escapeHtml(u.name || '-')} <span class="bo-text-subtle">${escapeHtml(u.username)}</span></span>
                    ${noteHtml}
                </label>`;
        }).join('') || '<div class="bo-text-subtle" style="padding:12px 4px;font-size:12.5px;">구성원이 없습니다.</div>';

        wrap.querySelectorAll('.bo-picker-check').forEach(c => {
            c.addEventListener('change', () => {
                const id = parseInt(c.value, 10);
                if (c.checked) pickerSelectedIds.add(id);
                else           pickerSelectedIds.delete(id);
                renderPickerSelected();
            });
        });
    }

    function renderPickerSelected() {
        const wrap = document.getElementById('bo-picker-selected');
        const ids = Array.from(pickerSelectedIds);
        if (!ids.length) {
            wrap.innerHTML = '<div class="bo-text-subtle" style="padding:12px 4px;font-size:12.5px;">선택된 구성원이 없습니다.</div>';
            return;
        }
        // ids 를 모든 known users(picker source 누적) 에서 lookup. 새로 fetch 가 부담스러우니 source 기반.
        const known = new Map(pickerSourceUsers.map(u => [u.id, u]));
        wrap.innerHTML = ids.map(id => {
            const u = known.get(id);
            const label = u ? `${escapeHtml(u.name)} <span class="bo-text-subtle">${escapeHtml(u.username)}</span>` : `#${id}`;
            return `
                <div style="display:flex;justify-content:space-between;align-items:center;padding:6px 4px;border-bottom:1px solid var(--bo-border-soft);">
                    <span>${label}</span>
                    <button type="button" class="bo-btn bo-btn-sm" data-pick-remove="${id}">제거</button>
                </div>`;
        }).join('');
        wrap.querySelectorAll('[data-pick-remove]').forEach(b => {
            b.addEventListener('click', () => {
                pickerSelectedIds.delete(parseInt(b.dataset.pickRemove, 10));
                renderPickerSource();
                renderPickerSelected();
            });
        });
    }

    document.getElementById('bo-picker-clear').addEventListener('click', () => {
        pickerSelectedIds.clear();
        renderPickerSource();
        renderPickerSelected();
    });

    document.getElementById('bo-picker-confirm').addEventListener('click', async () => {
        const ids = Array.from(pickerSelectedIds);
        if (!ids.length) {
            BO.toast('1명 이상 선택해 주세요.', 'error');
            return;
        }
        const res = await BO.fetchJSON(
            `/backoffice/api/organizations/${currentOrgId}/assign/`,
            { method: 'POST', body: JSON.stringify({ user_ids: ids }) },
        );
        if (!res.ok) {
            BO.toast(res.data.error || '추가 실패', 'error');
            return;
        }
        BO.toast(`${res.data.assigned}명이 추가되었습니다.`, 'success');
        closeModal(pickerModal);
        await loadOrgDetail(currentOrgId);
    });

    // ───────────────────── 부서 이동 ─────────────────────
    btnMove.addEventListener('click', () => {
        const wrap = document.getElementById('bo-move-tree');
        wrap.innerHTML = BOOT.departments
            .filter(d => d.id !== currentOrgId)
            .map(d => `
                <li class="bo-org-tree-item ${d.is_unassigned ? 'is-unassigned' : ''}" data-move-to="${d.id}">
                    ${escapeHtml(d.name)}
                </li>
            `).join('');
        let chosen = null;
        wrap.querySelectorAll('.bo-org-tree-item').forEach(li => {
            li.addEventListener('click', () => {
                wrap.querySelectorAll('.bo-org-tree-item').forEach(x => x.classList.remove('is-active'));
                li.classList.add('is-active');
                chosen = parseInt(li.dataset.moveTo, 10);
                document.getElementById('bo-move-confirm').disabled = false;
            });
        });
        document.getElementById('bo-move-confirm').onclick = async () => {
            if (!chosen) return;
            const ids = selectedMemberIds();
            const res = await BO.fetchJSON(
                `/backoffice/api/organizations/${chosen}/assign/`,
                { method: 'POST', body: JSON.stringify({ user_ids: ids }) },
            );
            if (!res.ok) {
                BO.toast(res.data.error || '이동 실패', 'error');
                return;
            }
            BO.toast(`${res.data.assigned}명이 이동되었습니다.`, 'success');
            closeModal(moveModal);
            await loadOrgDetail(currentOrgId);
        };
        document.getElementById('bo-move-confirm').disabled = true;
        openModal(moveModal);
    });

    // ───────────────────── 소속 제외 ─────────────────────
    btnRemove.addEventListener('click', async () => {
        const ids = selectedMemberIds();
        if (!ids.length) return;
        const ok = await BO.confirm(`선택한 ${ids.length}명을 '조직 없음' 으로 이동하시겠습니까?`);
        if (!ok) return;
        const res = await BO.fetchJSON(
            `/backoffice/api/organizations/${currentOrgId}/remove/`,
            { method: 'POST', body: JSON.stringify({ user_ids: ids }) },
        );
        if (!res.ok) {
            BO.toast(res.data.error || '제외 실패', 'error');
            return;
        }
        BO.toast(`${res.data.removed}명이 제외되었습니다.`, 'success');
        await loadOrgDetail(currentOrgId);
    });

    // ───────────────────── 조직장 임명 ─────────────────────
    btnLeader.addEventListener('click', async () => {
        const ids = selectedMemberIds();
        if (ids.length !== 1) return;
        const ok = await BO.confirm('선택한 사용자를 이 부서의 조직장으로 임명하시겠습니까?');
        if (!ok) return;
        const res = await BO.fetchJSON(
            `/backoffice/api/organizations/${currentOrgId}/set-leader/`,
            { method: 'POST', body: JSON.stringify({ user_id: ids[0] }) },
        );
        if (!res.ok) {
            BO.toast(res.data.error || '임명 실패', 'error');
            return;
        }
        BO.toast('조직장이 임명되었습니다.', 'success');
        await loadOrgDetail(currentOrgId);
    });

    // ───────────────────── 유틸 ─────────────────────
    function escapeHtml(s) {
        if (s == null) return '';
        return String(s)
            .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
    }
    function renderStatusBadge(status) {
        const map = {
            active:   ['bo-badge-status-active', '사용'],
            locked:   ['bo-badge-status-locked', '잠금'],
            disabled: ['bo-badge-status-disabled', '비활성'],
        };
        const [cls, label] = map[status] || map.disabled;
        return `<span class="bo-badge ${cls}">${label}</span>`;
    }

    // ───────────────────── 초기 로드 — 첫 부서 자동 선택 ─────────────────────
    const firstItem = treeEl.querySelector('.bo-org-tree-item');
    if (firstItem) firstItem.click();
})();
