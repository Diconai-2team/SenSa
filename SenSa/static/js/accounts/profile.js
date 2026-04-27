/**
 * accounts/profile.js — 내 정보 페이지 + 비밀번호 변경 모달
 *
 * [책임]
 *   1. "비밀번호 변경" 버튼 → 모달 열기
 *   2. 각 input X 버튼 → 필드 비우기
 *   3. 실시간 유효성 검사 (input 이벤트)
 *   4. 취소 버튼 / ESC / 백드롭 → 모달 닫기
 *   5. 변경 완료 버튼 → 서버 POST
 *      - 성공: 완료 모달 표시 → 확인 → 내 정보 페이지 복귀
 *      - 실패: 서버 에러를 각 필드에 매핑
 */
(function () {
  'use strict';

  var init = window.PROFILE_INIT || {};
  if (!init.passwordChangeUrl) {
    console.error('[profile] PROFILE_INIT 미정의');
    return;
  }

  // ─────────────────────────────────────────────────────────
  // DOM
  // ─────────────────────────────────────────────────────────
  var btnOpen     = document.getElementById('btn-open-pw-modal');
  var modal       = document.getElementById('pw-modal');
  var btnCancel   = document.getElementById('btn-pw-cancel');
  var btnSubmit   = document.getElementById('btn-pw-submit');

  var doneModal   = document.getElementById('pw-done-modal');
  var btnDoneOk   = document.getElementById('btn-pw-done-confirm');

  var inputCurrent = document.getElementById('pw-current');
  var inputNew     = document.getElementById('pw-new');
  var inputConfirm = document.getElementById('pw-confirm');

  // 필드 키 ↔ input 매핑
  var FIELDS = {
    current_password:      inputCurrent,
    new_password:          inputNew,
    new_password_confirm:  inputConfirm,
  };

  // 기본 안내 문구 (에러 해제 시 복구용)
  var DEFAULT_HINT = {
    current_password:     '*본인 확인을 위해 현재 사용 중인 비밀번호를 입력해 주세요.',
    new_password:         '*영문, 숫자, 특수문자 조합으로 8~16자 이내로 입력해 주세요.',
    new_password_confirm: '*위에서 입력한 신규 비밀번호를 다시 한번 입력해 주세요.',
  };

  // 디자인 시안 기준 비밀번호 규칙 (8~16자 영문+숫자+특수문자)
  var PW_RE = /^(?=.*[A-Za-z])(?=.*\d)(?=.*[~!@#$%^&*()_\-+={}\[\]|\\:;"'<>,.?/])[A-Za-z\d~!@#$%^&*()_\-+={}\[\]|\\:;"'<>,.?/]{8,16}$/;

  // ─────────────────────────────────────────────────────────
  // 모달 열기/닫기
  // ─────────────────────────────────────────────────────────
  btnOpen.addEventListener('click', openModal);
  btnCancel.addEventListener('click', closeModal);
  modal.addEventListener('click', function (e) {
    if (e.target === modal) closeModal();
  });
  document.addEventListener('keydown', function (e) {
    if (e.key === 'Escape' && !modal.hidden) closeModal();
  });

  function openModal() {
    resetForm();
    modal.hidden = false;
    setTimeout(function () { inputCurrent.focus(); }, 50);
  }

  function closeModal() {
    modal.hidden = true;
    resetForm();
  }

  function resetForm() {
    Object.keys(FIELDS).forEach(function (key) {
      FIELDS[key].value = '';
      clearFieldError(key);
    });
    btnSubmit.disabled = false;
    btnSubmit.textContent = '변경 완료';
  }

  // ─────────────────────────────────────────────────────────
  // X 클리어 버튼
  // ─────────────────────────────────────────────────────────
  document.querySelectorAll('.pw-input-clear').forEach(function (btn) {
    btn.addEventListener('click', function () {
      var id = btn.getAttribute('data-clear-target');
      var input = document.getElementById(id);
      if (input) {
        input.value = '';
        input.focus();
        // 관련 필드 에러 해제
        var field = findFieldKeyByInputId(id);
        if (field) clearFieldError(field);
      }
    });
  });

  function findFieldKeyByInputId(id) {
    for (var key in FIELDS) {
      if (FIELDS[key] && FIELDS[key].id === id) return key;
    }
    return null;
  }

  // ─────────────────────────────────────────────────────────
  // 실시간 유효성 검사 (입력 중에 에러 해제 / 재검증)
  // ─────────────────────────────────────────────────────────
  Object.keys(FIELDS).forEach(function (key) {
    FIELDS[key].addEventListener('input', function () {
      // 입력이 들어오면 일단 에러 해제 (사용자가 수정 중이므로 덜 방해)
      clearFieldError(key);

      // 신규비번과 확인 필드는 서로 의존관계 → 재검증
      if (key === 'new_password' || key === 'new_password_confirm') {
        maybeValidatePair();
      }
    });
  });

  function maybeValidatePair() {
    var newPw = inputNew.value;
    var confirmPw = inputConfirm.value;
    // 둘 다 값이 있고 불일치면 confirm 필드에 에러 표시
    if (newPw && confirmPw && newPw !== confirmPw) {
      setFieldError('new_password_confirm', '입력하신 신규 비밀번호와 일치하지 않습니다.');
    } else {
      clearFieldError('new_password_confirm');
    }
  }

  // ─────────────────────────────────────────────────────────
  // 에러 표시/해제
  // ─────────────────────────────────────────────────────────
  function setFieldError(fieldKey, message) {
    var fieldEl = document.querySelector('.pw-field[data-field="' + fieldKey + '"]');
    if (!fieldEl) return;
    fieldEl.classList.add('has-error');
    var hint = fieldEl.querySelector('.pw-hint');
    if (hint) hint.textContent = message;
  }

  function clearFieldError(fieldKey) {
    var fieldEl = document.querySelector('.pw-field[data-field="' + fieldKey + '"]');
    if (!fieldEl) return;
    fieldEl.classList.remove('has-error');
    var hint = fieldEl.querySelector('.pw-hint');
    if (hint) hint.textContent = DEFAULT_HINT[fieldKey];
  }

  // ─────────────────────────────────────────────────────────
  // 제출 (변경 완료)
  // ─────────────────────────────────────────────────────────
  btnSubmit.addEventListener('click', handleSubmit);

  function handleSubmit() {
    var currentPw = inputCurrent.value;
    var newPw = inputNew.value;
    var confirmPw = inputConfirm.value;

    // 클라 사전 검증 — 서버에도 동일 검증 있지만 UX 상 즉시 피드백
    var preErrors = {};

    if (!currentPw) {
      preErrors.current_password = '현재 사용 중인 비밀번호를 입력해 주세요.';
    }
    if (!newPw) {
      preErrors.new_password = '새로운 비밀번호를 입력해 주세요.';
    } else if (!PW_RE.test(newPw)) {
      preErrors.new_password = '8~16자의 영문, 숫자, 특수문자를 조합하여 입력해 주세요.';
    } else if (currentPw && newPw === currentPw) {
      preErrors.new_password = '현재 사용 중인 비밀번호는 신규 비밀번호로 사용할 수 없습니다.';
    }
    if (!confirmPw) {
      preErrors.new_password_confirm = '비밀번호 확인을 위해 한 번 더 입력해 주세요.';
    } else if (newPw && newPw !== confirmPw) {
      preErrors.new_password_confirm = '입력하신 신규 비밀번호와 일치하지 않습니다.';
    }

    // 사전 에러가 있으면 모두 표시 후 중단
    if (Object.keys(preErrors).length > 0) {
      Object.keys(preErrors).forEach(function (k) {
        setFieldError(k, preErrors[k]);
      });
      // 첫 에러 필드로 포커스
      var firstKey = Object.keys(preErrors)[0];
      if (FIELDS[firstKey]) FIELDS[firstKey].focus();
      return;
    }

    // 서버 전송
    btnSubmit.disabled = true;
    btnSubmit.textContent = '처리 중...';

    fetch(init.passwordChangeUrl, {
      method: 'POST',
      credentials: 'include',
      headers: {
        'Content-Type': 'application/json',
        'X-CSRFToken': getCsrfToken(),
      },
      body: JSON.stringify({
        current_password: currentPw,
        new_password: newPw,
        new_password_confirm: confirmPw,
      }),
    })
      .then(function (res) {
        return res.json().then(function (body) {
          return { ok: res.ok, body: body };
        });
      })
      .then(function (r) {
        if (r.ok) {
          showDoneModal();
        } else if (r.body && r.body.errors) {
          // 서버 필드별 에러 매핑
          Object.keys(r.body.errors).forEach(function (k) {
            setFieldError(k, r.body.errors[k]);
          });
          // 첫 에러로 포커스
          var firstKey = Object.keys(r.body.errors)[0];
          if (FIELDS[firstKey]) FIELDS[firstKey].focus();
        } else {
          alert((r.body && r.body.detail) || '비밀번호 변경에 실패했습니다.');
        }
      })
      .catch(function (err) {
        console.error('[profile] pw change error', err);
        alert('네트워크 오류로 비밀번호 변경에 실패했습니다.');
      })
      .finally(function () {
        btnSubmit.disabled = false;
        btnSubmit.textContent = '변경 완료';
      });
  }

  // ─────────────────────────────────────────────────────────
  // 완료 모달
  // ─────────────────────────────────────────────────────────
  function showDoneModal() {
    modal.hidden = true;        // 변경 모달 먼저 닫음
    doneModal.hidden = false;
    setTimeout(function () { btnDoneOk.focus(); }, 50);
  }

  btnDoneOk.addEventListener('click', function () {
    doneModal.hidden = true;
    // 내 정보 페이지 그대로 (리로드 불필요)
  });

  doneModal.addEventListener('click', function (e) {
    if (e.target === doneModal) doneModal.hidden = true;
  });

  // ─────────────────────────────────────────────────────────
  // CSRF
  // ─────────────────────────────────────────────────────────
  function getCsrfToken() {
    var meta = document.querySelector('meta[name="csrf-token"]');
    if (meta) return meta.getAttribute('content');
    var c = document.cookie.split(';').find(function (c) {
      return c.trim().startsWith('csrftoken=');
    });
    return c ? c.split('=')[1] : '';
  }

})();