from rest_framework.generics import ListAPIView
from rest_framework.views import APIView
from rest_framework.response import Response
from apps.users.serializers.users import UserInfoLoginSerializer, UserInfoSerializer
from apps.users.models import UserInfo
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.exceptions import ExpiredTokenError, TokenError
from django.core.cache import cache
# TODO: 修改包名
from Reflectance_api_service.utils.auth import TokenAuthenticate
from Reflectance_api_service.settings.status_code import StatusCode

# RSA 解密需要的包
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.backends import default_backend
import base64
from io import BytesIO
import random
import string
import uuid
import re
from PIL import Image, ImageDraw, ImageFont

from rest_framework_simplejwt.tokens import AccessToken

# ====================== 密钥路径（必须正确） ======================
import os
CURRENT_DIR = os.path.dirname(__file__)

PRIVATE_KEY_PATH = os.path.join(CURRENT_DIR, "paper_review_system", "keys", "private_key.pem")
PUBLIC_KEY_PATH = os.path.join(CURRENT_DIR, "paper_review_system", "keys", "public_key.pem")

# ====================== 加载私钥（全局加载一次） ======================
def load_private_key():
    with open(PRIVATE_KEY_PATH, "rb") as f:
        private_key = serialization.load_pem_private_key(
            f.read(),
            password=None,
            backend=default_backend()
        )
    return private_key


# 全局加载私钥
private_key = load_private_key()

ADMIN_DEPARTMENTS = {"管理员", "admin", "administrator"}

CAPTCHA_CACHE_PREFIX = "login_captcha:"
CAPTCHA_EXPIRE_SECONDS = 300


def build_captcha_code(length=4):
    return "".join(random.choices(string.digits, k=length))


def build_captcha_image_base64(captcha_code):
    width, height = 120, 40
    image = Image.new("RGB", (width, height), (245, 247, 250))
    draw = ImageDraw.Draw(image)

    for _ in range(6):
        x1 = random.randint(0, width)
        y1 = random.randint(0, height)
        x2 = random.randint(0, width)
        y2 = random.randint(0, height)
        draw.line((x1, y1, x2, y2), fill=(180, 190, 200), width=1)

    for _ in range(80):
        x = random.randint(0, width - 1)
        y = random.randint(0, height - 1)
        draw.point((x, y), fill=(random.randint(120, 200), random.randint(120, 200), random.randint(120, 200)))

    try:
        font = ImageFont.truetype("arial.ttf", 26)
    except OSError:
        font = ImageFont.load_default()

    for index, char in enumerate(captcha_code):
        x = 16 + index * 24 + random.randint(-2, 2)
        y = random.randint(5, 10)
        color = (
            random.randint(20, 90),
            random.randint(40, 120),
            random.randint(80, 160),
        )
        draw.text((x, y), char, font=font, fill=color)

    buffer = BytesIO()
    image.save(buffer, format="PNG")
    return "data:image/png;base64," + base64.b64encode(buffer.getvalue()).decode("ascii")

"""生成验证码"""
class CaptchaGenerateView(APIView):
    authentication_classes = []
    permission_classes = []

    def get(self, request):
        captcha_id = uuid.uuid4().hex
        captcha_code = build_captcha_code()
        cache.set(
            CAPTCHA_CACHE_PREFIX + captcha_id,
            captcha_code,
            CAPTCHA_EXPIRE_SECONDS,
        )

        return Response({
            "code": 200,
            "msg": "验证码生成成功",
            "data": {
                "captcha_id": captcha_id,
                "captcha_image": build_captcha_image_base64(captcha_code),
                "expire_seconds": CAPTCHA_EXPIRE_SECONDS,
            }
        })

"""校验验证码"""
class CaptchaVerifyView(APIView):
    authentication_classes = []
    permission_classes = []

    def post(self, request):
        captcha_id = request.data.get("captcha_id")
        captcha = request.data.get("captcha")

        if not captcha_id or not captcha:
            return Response(
                {"code": 400, "msg": "缺少参数 captcha_id 或 captcha", "data": {}},
                status=400,
            )

        cache_key = CAPTCHA_CACHE_PREFIX + str(captcha_id)
        cached_captcha = cache.get(cache_key)
        if cached_captcha is None:
            return Response(
                {"code": 1018, "msg": "验证码不存在或已过期", "data": {}},
                status=400,
            )

        if str(cached_captcha).lower() != str(captcha).strip().lower():
            return Response(
                {"code": 1017, "msg": "验证码不正确", "data": {}},
                status=400,
            )

        cache.delete(cache_key)
        return Response({
            "code": 200,
            "msg": "验证码验证成功",
            "data": {}
        })


def is_admin_user(user):
    department = str(getattr(user, "department", "") or "").strip().lower()
    return department in ADMIN_DEPARTMENTS


def permission_denied_response():
    return Response({"code": 403, "msg": "没有权限"}, status=403)

# ====================== RSA 解密函数（接收前端传的 base64 密码） ======================
def rsa_decrypt_password(encrypted_base64):
    try:
        # 1. 先把前端传来的 base64 字符串解码
        encrypted_bytes = base64.b64decode(encrypted_base64)

        # 2. RSA 私钥解密
        decrypted_bytes = private_key.decrypt(
            encrypted_bytes,
            padding.OAEP(
                mgf=padding.MGF1(algorithm=hashes.SHA256()),
                algorithm=hashes.SHA256(),
                label=None
            )
        )
        return decrypted_bytes.decode("utf-8")
    except Exception as e:
        # 解密失败（密码格式错误/密钥不匹配）
        return None


# ====================== 登录接口 ======================
class UserInfoLoginView(APIView):
    def post(self, request):
        username = request.data.get("username")
        encrypted_password = request.data.get("password")  # 前端传的是【RSA+Base64加密密码】

        # 1. 校验非空
        if not username or not encrypted_password:
            return Response({'code': 400, 'msg': "用户名或密码不能为空"})

        # 2. 查询用户
        account = UserInfo.objects.filter(username=username, is_delete=False).first()
        if account is None:
            return Response({'code': 400, 'msg': "用户不存在"})

        # ====================== 核心：解密前端传来的密码 ======================
        password = rsa_decrypt_password(encrypted_password)
        if password is None:
            return Response({'code': 1004, 'msg': "密码解密失败，请检查加密方式"})

        # 3. 密码校验
        if account.password != password:
            return Response({'code': 400, 'msg': "密码错误"})

        # 4. 生成 JWT 令牌
        refresh = RefreshToken.for_user(account)

        return Response({
            'code': 200,
            'msg': "登录成功",
            'data': {
                'user_id': account.id,
                'username': account.username,
                'department': account.department,
                'refresh': str(refresh),
                'access': str(refresh.access_token),
            }
        })

class UserTokenRefreshView(APIView):
    def post(self, request):
        refresh_token = request.data.get("refresh")
        if not refresh_token:
            return Response({"code": 400, "msg": "缺少参数 refresh"}, status=400)

        try:
            refresh = RefreshToken(refresh_token)
            user_id = refresh.get("user_id")
            user = UserInfo.objects.filter(id=user_id, is_delete=False).first()
            if user is None:
                return Response(
                    {"code": StatusCode.NOT_AUTHENTICATED_CODE, "msg": "用户不存在", "data": {}},
                    status=401,
                )

            return Response(
                {
                    "code": 200,
                    "msg": "刷新成功",
                    "data": {
                        "access": str(refresh.access_token),
                    },
                }
            )
        except ExpiredTokenError:
            return Response(
                {"code": StatusCode.TOKEN_EXPIRED_CODE, "msg": "token已过期", "data": {}},
                status=401,
            )
        except TokenError as exc:
            if "expired" in str(exc).lower():
                return Response(
                    {"code": StatusCode.TOKEN_EXPIRED_CODE, "msg": "token已过期", "data": {}},
                    status=401,
                )
            return Response(
                {"code": StatusCode.NOT_AUTHENTICATED_CODE, "msg": "refresh token无效", "data": {}},
                status=401,
            )


def validate_password_strength(password):
    """
    密码强度校验：
    1. 长度 8-20 位
    2. 至少包含 1 个大写字母
    3. 至少包含 1 个小写字母
    4. 至少包含 1 个数字
    5. 至少包含 1 个特殊字符
    6. 不允许包含空格
    """

    if not isinstance(password, str):
        return False, "密码格式错误"

    if len(password) < 8 or len(password) > 20:
        return False, "密码长度必须为8-20位"

    if re.search(r"\s", password):
        return False, "密码不能包含空格"

    if not re.search(r"[A-Z]", password):
        return False, "密码必须包含至少一个大写字母"

    if not re.search(r"[a-z]", password):
        return False, "密码必须包含至少一个小写字母"

    if not re.search(r"\d", password):
        return False, "密码必须包含至少一个数字"

    if not re.search(r"[!@#$%^&*()_+\-=\[\]{};':\"\\|,.<>/?]", password):
        return False, "密码必须包含至少一个特殊字符"

    return True, ""

def get_password_strength(password):
    """
    返回密码强度：
    weak   弱
    medium 中
    strong 强
    """

    if not isinstance(password, str):
        return "weak", "密码格式错误"

    if re.search(r"\s", password):
        return "weak", "密码不能包含空格"

    score = 0

    # 长度评分
    if len(password) >= 8:
        score += 1
    if len(password) >= 12:
        score += 1

    # 字符类型评分
    if re.search(r"[A-Z]", password):
        score += 1

    if re.search(r"[a-z]", password):
        score += 1

    if re.search(r"\d", password):
        score += 1

    if re.search(r"[!@#$%^&*()_+\-=\[\]{};':\"\\|,.<>/?]", password):
        score += 1

    # 长度不足直接弱
    if len(password) < 8:
        return "weak", "密码长度不能少于8位"

    if score <= 3:
        return "weak", "密码强度弱"

    if score <= 5:
        return "medium", "密码强度中"

    return "strong", "密码强度强"

class CreateUserInfoView(APIView):
    authentication_classes = [TokenAuthenticate]

    def post(self, request):
        if not is_admin_user(request.user):
            return permission_denied_response()

        username = request.data.get("username")
        password = request.data.get("password")
        department = request.data.get("department")

        # 验证必填字段
        if not username or not password or not department:
            return Response({'code': 400, 'msg': "用户名、密码和部门不能为空"})

        # 校验密码基础规则
        is_valid, msg = validate_password_strength(password)
        if not is_valid:
            return Response({'code': 400, 'msg': msg})
        # 校验密码强度
        strength, msg = get_password_strength(password)
        if strength == "weak":
            return Response({
                'code': 400,
                'msg': "密码强度过低，请使用更复杂的密码",
                'strength': strength
            })

        # 检查用户名是否已存在
        if UserInfo.objects.filter(username=username).exists():
            return Response({'code': 400, 'msg': "用户名已存在"})

        # ====================== 核心：解密前端传来的密码 ======================
        password = rsa_decrypt_password(password)
        if password is None:
            return Response({'code': 400, 'msg': "密码解密失败，请检查加密方式"})

        # 创建新用户
        try:
            user = UserInfo.objects.create(
                username=username,
                password=password,
                department=department
            )
            return Response({
                'code': 200,
                'msg': "用户创建成功"
            })
        except Exception as e:
            return Response({'code': 400, 'msg': f"用户创建失败: {str(e)}"})



class DeleteUserView(APIView):
    authentication_classes = [TokenAuthenticate]

    def get(self, request):
        if not is_admin_user(request.user):
            return permission_denied_response()

        user_id = request.query_params.get("id")

        if not user_id:
            return Response({'code': 400, 'msg': "用户ID不能为空"})
        account = UserInfo.objects.filter(id=user_id, is_delete=False).first()
        if account is None:
            return Response({'code': 400, 'msg': "用户不存在"})
        account.is_delete = True
        account.save()
        return Response({
            'code': 200,
            'msg': "删除成功"
        })


class UpdateUserView(APIView):
    authentication_classes = [TokenAuthenticate]

    def put(self, request):
        user_id = request.data.get("id")
        old_password = request.data.get("old_password")
        new_password = request.data.get("new_password")

        if not user_id:
            return Response({'code': 400, 'msg': "用户ID不能为空"})

        try:
            user_id = int(user_id)
        except (TypeError, ValueError):
            return Response({'code': 400, 'msg': "用户ID格式错误"})

        if user_id != request.user.id:
            return permission_denied_response()

        if not old_password or not new_password:
            return Response({'code': 1004, 'msg': "旧密码和新密码不能为空"})

        # ====================== 核心：解密前端传来的密码 ======================
        old_password = rsa_decrypt_password(old_password)
        if old_password is None:
            return Response({'code': 400, 'msg': "密码解密失败，请检查加密方式"})

        # ====================== 核心：解密前端传来的密码 ======================
        new_password = rsa_decrypt_password(new_password)
        if new_password is None:
            return Response({'code': 400, 'msg': "密码解密失败，请检查加密方式"})

        account = UserInfo.objects.filter(id=user_id, is_delete=False).first()
        if account is None:
            return Response({'code': 400, 'msg': "用户不存在"})

        # 验证旧密码是否正确
        if account.password != old_password:
            return Response({'code': 400, 'msg': "旧密码错误"})

        # 校验密码基础规则
        is_valid, msg = validate_password_strength(new_password)
        if not is_valid:
            return Response({'code': 400, 'msg': msg})

        # 校验密码强度
        strength, msg = get_password_strength(new_password)
        if strength == "weak":
            return Response({
                'code': 400,
                'msg': "密码强度过低，请使用更复杂的密码",
                'strength': strength
            })

        if account.password == new_password:
            return Response({'code': 400, 'msg': "新密码不能与旧密码相同"})

        # 更新密码
        account.password = new_password
        account.save()

        return Response({
            'code': 200,
            'msg': "密码修改成功"
        })



class UserListView(APIView):
    authentication_classes = [TokenAuthenticate]

    def get(self, request):
        if not is_admin_user(request.user):
            return permission_denied_response()

        queryset = UserInfo.objects.filter(is_delete=False)
        serializer = UserInfoSerializer(queryset, many=True)
        return Response({
            "code": 200,
            "msg": "获取成功",
            "data": serializer.data
        })
