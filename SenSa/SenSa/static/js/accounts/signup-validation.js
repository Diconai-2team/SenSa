/**
 * 회원가입 폼 프론트엔드 유효성 검사
 * - 아이디 형식/길이 검증
 * - 비밀번호 길이/일치 검증
 * - 실시간 비밀번호 일치 표시
 */
(function () {
    'use strict';

    const form = document.getElementById('signup-form');
    if (!form) return;

    const usernameInput = document.getElementById('username');
    const passwordInput = document.getElementById('password');
    const passwordConfirmInput = document.getElementById('password_confirm');

    // === 제출 시 검증 ===
    form.addEventListener('submit', function (e) {
        const username = usernameInput.value.trim();
        const password = passwordInput.value;
        const passwordConfirm = passwordConfirmInput.value;

        // 아이디 형식
        if (!/^[a-zA-Z0-9_]+$/.test(username)) {
            e.preventDefault();
            alert('아이디는 영문, 숫자, 언더스코어(_)만 사용 가능합니다.');
            return false;
        }
        if (username.length < 4 || username.length > 20) {
            e.preventDefault();
            alert('아이디는 4~20자여야 합니다.');
            return false;
        }

        // 비밀번호 길이
        if (password.length < 8) {
            e.preventDefault();
            alert('비밀번호는 8자 이상이어야 합니다.');
            return false;
        }

        // 비밀번호 일치
        if (password !== passwordConfirm) {
            e.preventDefault();
            alert('비밀번호가 일치하지 않습니다.');
            return false;
        }
    });

    // === 실시간 비밀번호 일치 표시 ===
    function checkPasswordMatch() {
        if (!passwordConfirmInput.value) return;
        if (passwordInput.value !== passwordConfirmInput.value) {
            passwordConfirmInput.classList.add('has-error');
        } else {
            passwordConfirmInput.classList.remove('has-error');
        }
    }

    passwordInput.addEventListener('input', checkPasswordMatch);
    passwordConfirmInput.addEventListener('input', checkPasswordMatch);
})();