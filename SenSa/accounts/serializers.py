from rest_framework import serializers
# DRF의 시리얼라이저 클래스 — 요청 검증/응답 직렬화의 핵심 모듈이야
from django.contrib.auth import get_user_model, authenticate
# get_user_model: settings.AUTH_USER_MODEL을 안전하게 가져오는 헬퍼
# authenticate: username/password로 사용자를 검증해서 User 객체 또는 None을 돌려주는 함수야
from django.contrib.auth.password_validation import validate_password
# Django settings의 AUTH_PASSWORD_VALIDATORS를 통과시키는 표준 비밀번호 검증기야
import re
# 정규표현식 — username 형식 검증에 사용해
User = get_user_model()
# 모듈 로드 시점에 커스텀 User 클래스를 한 번 가져와 캐싱 — 이후 User.objects.* 처럼 사용해


class LoginSerializer(serializers.Serializer):
    # 로그인 요청 검증 전용 시리얼라이저 — 모델과 직접 연결되지 않으니 일반 Serializer를 상속해
    """
    로그인 요청 시리얼라이저.
    백엔드 측 유효성 검사를 담당한다.
    """

    username = serializers.CharField()
    # 아이디 입력 필드 — 필수
    password = serializers.CharField(
    # 비밀번호 입력 필드 — 응답에는 절대 포함되지 않게 write_only로 막아
        write_only=True,
        # 직렬화 시 응답 JSON에서 제외 — 보안상 필수 옵션이야
        style={'input_type': 'password'}
        # browsable API 폼에서 password 타입 input으로 렌더링되도록 힌트를 줘
    )

    def validate(self, data):
        # 여러 필드를 함께 검증할 때 호출되는 메서드 — 인증 로직을 여기서 처리해
        username = data.get('username', '').strip()
        # 아이디 앞뒤 공백 제거 — 사용자 실수로 인한 인증 실패를 줄여
        password = data.get('password', '')

        # 빈 값 체크
        if not username or not password:
            raise serializers.ValidationError(
                "아이디와 비밀번호를 입력해주세요."
            )
            # 둘 중 하나라도 비어있으면 즉시 검증 실패 — 400 응답으로 이어져

        # 아이디 길이 (메인 기능 정의 1-2: 4~20자)
        if len(username) < 4 or len(username) > 20:
            raise serializers.ValidationError(
                "아이디는 4~20자여야 합니다."
            )
            # SignupSerializer와 동일한 길이 정책 — 정책 일관성 유지를 위함

        # 인증 시도
        user = authenticate(username=username, password=password)
        # Django 인증 백엔드에 위임 — 비밀번호 해시 검증까지 한 번에 처리해
        if not user:
            raise serializers.ValidationError(
                "아이디 또는 비밀번호가 올바르지 않습니다."
            )
            # 어느 쪽이 틀렸는지 노출하지 않는 통합 메시지 — 사용자 열거 공격 방지 베스트 프랙티스야

        if not user.is_active:
            raise serializers.ValidationError(
                "비활성화된 계정입니다. 관리자에게 문의하세요."
            )
            # is_active=False 계정은 여기서 차단 — is_locked 체크는 뷰에서 별도 처리해

        data['user'] = user
        # 검증된 user 객체를 validated_data에 실어서 뷰로 전달
        return data


class UserSerializer(serializers.ModelSerializer):
    # User 모델 → JSON 응답으로 직렬화하는 시리얼라이저 — /me 등에서 사용해
    """
    사용자 정보 반환용 시리얼라이저.
    /api/accounts/me/ 응답에 사용된다.
    """
    role_display = serializers.CharField(source='get_role_display', read_only=True)
    # role의 한국어 라벨을 별도 필드로 노출 — 프론트가 mapping을 따로 안 만들어도 되도록 해

    class Meta:
        model = User
        # 직렬화 대상 모델 지정
        fields = [
        # 응답에 포함될 필드 화이트리스트 — password 같은 민감정보가 새지 않도록 명시적으로 나열
            'id', 'username', 'email',
            'role', 'role_display', 'department', 'phone',
            'is_active', 'is_staff',
            'date_joined', 'last_login',
        ]
        read_only_fields = ['id', 'date_joined', 'last_login', 'is_staff']
        # 클라이언트가 수정할 수 없게 잠그는 필드 — 권한 상승 공격 방지에 중요해

class SignupSerializer(serializers.ModelSerializer):
    # 회원가입 입력 검증 + 사용자 생성을 담당하는 시리얼라이저야
    """
    회원가입 시리얼라이저.
    ...(docstring 생략)...
    """

    password = serializers.CharField(
    # 비밀번호 필드 — 생성 시에만 받고 응답에는 절대 포함하지 않아
        write_only=True,
        required=True,
        validators=[validate_password],
        # Django 표준 비밀번호 정책 검증기 — 최소 길이/너무 흔한 비밀번호 등을 거름
        style={'input_type': 'password'}
    )
    password_confirm = serializers.CharField(
    # 확인용 비밀번호 — 모델 필드가 아니므로 ModelSerializer에 별도 선언 필요해
        write_only=True,
        required=True,
        style={'input_type': 'password'}
    )

    class Meta:
        model = User
        fields = ['username', 'password', 'password_confirm',
                  'email', 'department', 'phone']
        # 회원가입 시 클라이언트가 보낼 수 있는 필드 — role/is_staff 등은 의도적으로 제외했어
        extra_kwargs = {
        # 필드별 추가 옵션 — 모델 정의와 별개로 시리얼라이저 레벨에서 덮어써
            'email': {'required': False, 'allow_blank': True},
            'department': {'required': False, 'allow_blank': True},
            'phone': {'required': False, 'allow_blank': True},
            # 이 세 개는 선택 입력 — 비어 있어도 검증 통과
        }

    def validate_username(self, value):
        # username 단일 필드 검증 메서드 — DRF가 자동 호출해
        value = value.strip()
        # 앞뒤 공백 제거 후 검증

        # 길이 검증
        if len(value) < 4 or len(value) > 20:
            raise serializers.ValidationError("아이디는 4~20자여야 합니다.")

        # 형식 검증 (영문, 숫자, 언더스코어만)
        if not re.match(r"^[a-zA-Z0-9_]+$", value):
            raise serializers.ValidationError(
                "아이디는 영문, 숫자, 언더스코어(_)만 사용 가능합니다."
            )
            # 한글/특수문자/공백 차단 — URL/로그/검색 안전성 확보용 정책이야

        # 중복 검증
        if User.objects.filter(username=value).exists():
            raise serializers.ValidationError("이미 사용 중인 아이디입니다.")
            # 동시 가입 시 race condition 가능성 — DB unique 제약과 함께 다층 방어해야 안전해

        return value

    def validate_email(self, value):
        # 이메일 단일 필드 검증 — 선택 필드지만 입력했다면 중복 차단해
        if value and User.objects.filter(email=value).exists():
            raise serializers.ValidationError("이미 사용 중인 이메일입니다.")
        return value

    def validate(self, data):
        # 여러 필드 교차 검증 — 비밀번호 두 입력의 일치 여부를 확인해
        if data.get('password') != data.get('password_confirm'):
            raise serializers.ValidationError({
                'password_confirm': '비밀번호가 일치하지 않습니다.'
            })
            # 필드명 키로 감싸서 raise — 프론트가 어느 필드 에러인지 정확히 알 수 있어
        return data

    def create(self, validated_data):
        # 검증 통과한 데이터로 실제 User를 만드는 메서드 — serializer.save() 호출 시 실행돼
        validated_data.pop('password_confirm')
        # 확인용 필드는 DB에 없으므로 제거
        password = validated_data.pop('password')
        # 비밀번호는 평문 저장 금지 — set_password로 해시 처리하기 위해 따로 빼둬

        # 사용자 조작 불가 필드는 강제 고정
        user = User(**validated_data)
        # 나머지 필드로 인스턴스 생성 (아직 DB 저장 안 함)
        user.role = 'operator'
        # 회원가입 경로로 들어온 사용자는 무조건 '운영자' 등급 — 권한 상승 차단의 핵심 코드야
        user.is_staff = False
        # admin 사이트 접근 차단 — 명시적으로 False 박아둠
        user.is_superuser = False
        # 슈퍼유저 권한 차단 — 명시적으로 False 박아둠
        user.is_active = True
        # 가입 즉시 로그인 가능 (이메일 인증 절차 없음)

        user.set_password(password)
        # 비밀번호 해시화 — 절대 평문으로 user.password = ... 하면 안 돼
        user.save()
        # DB에 INSERT
        return user
