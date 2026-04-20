/**
 * 로그인 폼 프론트엔드 유효성 검사
 * 메인 기능 정의 1-2 구현
 */
(function () {
    'use strict';

    const form = document.getElementById('login-form');
    if (!form) return;

    form.addEventListener('submit', function (e) {
        const username = document.getElementById('username').value.trim();
        const password = document.getElementById('password').value;

        if (!username || !password) {
            e.preventDefault();
            alert('아이디와 비밀번호를 입력해주세요.');
            return false;
        }

        if (username.length < 4 || username.length > 20) {
            e.preventDefault();
            alert('아이디는 4~20자여야 합니다.');
            return false;
        }
    });
})();