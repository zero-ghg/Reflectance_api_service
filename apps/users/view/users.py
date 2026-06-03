from rest_framework.generics import ListAPIView
from rest_framework.views import APIView
from rest_framework.response import Response
from apps.users.serializers.users import UserInfoLoginSerializer, UserInfoSerializer
from apps.users.models import UserInfo
from rest_framework_simplejwt.tokens import RefreshToken
# TODO: 修改包名
from Reflectance_api_service.utils.auth import TokenAuthenticate


class UserInfoLoginView(APIView):
    def post(self, request):
        username = request.data.get("username")
        password = request.data.get("password")

        if not username or not password:
            return Response({'code': 1004, 'msg': "用户名或密码不能为空"})

        account = UserInfo.objects.filter(username=username, is_delete=False).first()

        if account is None:
            return Response({'code': 1004, 'msg': "用户不存在"})

        if account.password != password:
            return Response({'code': 1004, 'msg': "用户名或密码错误"})

        refresh = RefreshToken.for_user(account)

        return Response({
            'code': 200,
            'msg': "登录成功",
            'data': {
                'user_id': account.id,
                'username': account.username,
                'department':account.department,
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
