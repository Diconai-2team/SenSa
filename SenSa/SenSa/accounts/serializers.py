from rest_framework import serializers
from django.contrib.auth import get_user_model, authenticate
from django.contrib.auth.password_validation import validate_password  # 추가
import re
User = get_user_model()


class LoginSerializer(serializers.Serializer):
    """
    로그인 요청 시리얼라이저.
    백엔드 측 유효성 검사를 담당한다.
    """
    username = serializers.CharField()
    password = serializers.CharField(
        write_only=True,
        style={'input_type': 'password'}
    )

    def validate(self, data):
        username = data.get('username', '').strip()
        password = data.get('password', '')

        # 빈 값 체크
        if not username or not password:
            raise serializers.ValidationError(
                "아이디와 비밀번호를 입력해주세요."
            )

        # 아이디 길이 (메인 기능 정의 1-2: 4~20자)
        if len(username) < 4 or len(username) > 20:
            raise serializers.ValidationError(
                "아이디는 4~20자여야 합니다."
            )

        # 인증 시도
        user = authenticate(username=username, password=password)
        if not user:
            raise serializers.ValidationError(
                "아이디 또는 비밀번호가 올바르지 않습니다."
            )

        if not user.is_active:
            raise serializers.ValidationError(
                "비활성화된 계정입니다. 관리자에게 문의하세요."
            )

        data['user'] = user
        return data


class UserSerializer(serializers.ModelSerializer):
    """
    사용자 정보 반환용 시리얼라이저.
    /api/accounts/me/ 응답에 사용된다.
    """
    role_display = serializers.CharField(source='get_role_display', read_only=True)

    class Meta:
        model = User
        fields = [
            'id', 'username', 'email',
            'role', 'role_display', 'department', 'phone',
            'is_active', 'is_staff',
            'date_joined', 'last_login',
        ]
        read_only_fields = ['id', 'date_joined', 'last_login', 'is_staff']

class SignupSerializer(serializers.ModelSerializer):
    """
    회원가입 시리얼라이저.

    - username: 4~20자, 영문/숫자/_만 허용, 중복 체크
    - password: Django 기본 validator 통과
    - password_confirm: password와 일치 필수
    - role은 항상 'operator'로 고정 (사용자 조작 불가)
    """
    password = serializers.CharField(
        write_only=True,
        required=True,
        validators=[validate_password],
        style={'input_type': 'password'}
    )
    password_confirm = serializers.CharField(
        write_only=True,
        required=True,
        style={'input_type': 'password'}
    )

    class Meta:
        model = User
        fields = ['username', 'password', 'password_confirm',
                  'email', 'department', 'phone']
        extra_kwargs = {
            'email': {'required': False, 'allow_blank': True},
            'department': {'required': False, 'allow_blank': True},
            'phone': {'required': False, 'allow_blank': True},
        }

    def validate_username(self, value):
        value = value.strip()

        # 길이 검증
        if len(value) < 4 or len(value) > 20:
            raise serializers.ValidationError("아이디는 4~20자여야 합니다.")

        # 형식 검증 (영문, 숫자, 언더스코어만)
        if not re.match(r'^[a-zA-Z0-9_]+$', value):
            raise serializers.ValidationError(
                "아이디는 영문, 숫자, 언더스코어(_)만 사용 가능합니다."
            )

        # 중복 검증
        if User.objects.filter(username=value).exists():
            raise serializers.ValidationError("이미 사용 중인 아이디입니다.")

        return value

    def validate_email(self, value):
        # 선택 필드지만, 입력했다면 중복 체크 (선택적)
        if value and User.objects.filter(email=value).exists():
            raise serializers.ValidationError("이미 사용 중인 이메일입니다.")
        return value

    def validate(self, data):
        # 비밀번호 일치 검증
        if data.get('password') != data.get('password_confirm'):
            raise serializers.ValidationError({
                'password_confirm': '비밀번호가 일치하지 않습니다.'
            })
        return data

    def create(self, validated_data):
        # password_confirm은 DB 저장 대상 아니므로 제거
        validated_data.pop('password_confirm')
        password = validated_data.pop('password')

        # 사용자 조작 불가 필드는 강제 고정
        user = User(**validated_data)
        user.role = 'operator'          # ⚠️ 절대 다른 값으로 바꾸지 말 것
        user.is_staff = False
        user.is_superuser = False
        user.is_active = True

        user.set_password(password)
        user.save()
        return user