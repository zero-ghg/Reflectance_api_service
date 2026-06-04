from rest_framework.generics import ListAPIView
from rest_framework.views import APIView
from rest_framework.response import Response
from apps.users.serializers.users import UserInfoLoginSerializer, UserInfoSerializer
from apps.users.models import UserInfo
from rest_framework_simplejwt.tokens import RefreshToken
# TODO: 修改包名
from Reflectance_api_service.utils.auth import TokenAuthenticate

# RSA 解密需要的包
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.backends import default_backend
import base64

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
            return Response({'code': 1004, 'msg': "用户名或密码不能为空"})

        # 2. 查询用户
        account = UserInfo.objects.filter(username=username, is_delete=False).first()
        if account is None:
            return Response({'code': 1004, 'msg': "用户不存在"})

        # ====================== 核心：解密前端传来的密码 ======================
        password = rsa_decrypt_password(encrypted_password)
        if password is None:
            return Response({'code': 1004, 'msg': "密码解密失败，请检查加密方式"})

        # 3. 密码校验
        if account.password != password:
            return Response({'code': 1004, 'msg': "密码错误"})

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

class CreateUserInfoView(APIView):
    def post(self, request):
        username = request.data.get("username")
        password = request.data.get("password")
        department = request.data.get("department")

        # 验证必填字段
        if not username or not password or not department:
            return Response({'code': 1004, 'msg': "用户名、密码和部门不能为空"})

        # 检查用户名是否已存在
        if UserInfo.objects.filter(username=username).exists():
            return Response({'code': 1004, 'msg': "用户名已存在"})

        # ====================== 核心：解密前端传来的密码 ======================
        password = rsa_decrypt_password(password)
        if password is None:
            return Response({'code': 1004, 'msg': "密码解密失败，请检查加密方式"})

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
            return Response({'code': 1005, 'msg': f"用户创建失败: {str(e)}"})



class DeleteUserView(APIView):
    def get(self, request):
        user_id = request.query_params.get("id")

        if not user_id:
            return Response({'code': 1004, 'msg': "用户ID不能为空"})
        account = UserInfo.objects.filter(id=user_id, is_delete=False).first()
        if account is None:
            return Response({'code': 1004, 'msg': "用户不存在"})
        account.is_delete = True
        account.save()
        return Response({
            'code': 200,
            'msg': "删除成功"
        })


class UpdateUserView(APIView):
    def put(self, request):
        user_id = request.data.get("id")
        old_password = request.data.get("old_password")
        new_password = request.data.get("new_password")

        if not user_id:
            return Response({'code': 1004, 'msg': "用户ID不能为空"})

        if not old_password or not new_password:
            return Response({'code': 1004, 'msg': "旧密码和新密码不能为空"})

        # ====================== 核心：解密前端传来的密码 ======================
        old_password = rsa_decrypt_password(old_password)
        if old_password is None:
            return Response({'code': 1004, 'msg': "密码解密失败，请检查加密方式"})

        # ====================== 核心：解密前端传来的密码 ======================
        new_password = rsa_decrypt_password(new_password)
        if new_password is None:
            return Response({'code': 1004, 'msg': "密码解密失败，请检查加密方式"})

        account = UserInfo.objects.filter(id=user_id, is_delete=False).first()
        if account is None:
            return Response({'code': 1004, 'msg': "用户不存在"})

        # 验证旧密码是否正确
        if account.password != old_password:
            return Response({'code': 1004, 'msg': "旧密码错误"})

        # 更新密码
        account.password = new_password
        account.save()

        return Response({
            'code': 200,
            'msg': "密码修改成功"
        })



class UserListView(APIView):
    permission_classes = []
    def get(self, request):
        queryset = UserInfo.objects.filter(is_delete=False)
        serializer = UserInfoSerializer(queryset, many=True)
        return Response({
            "code": 200,
            "msg": "获取成功",
            "data": serializer.data
        })
