from django.db import models
from django.utils import timezone
from Reflectance_api_service.utils.models import BaseModel


class UserInfo(BaseModel):
    username = models.CharField(unique=True, max_length=32, verbose_name="用户名")
    password = models.CharField(max_length=32, verbose_name="密码")
    department = models.CharField(max_length=32, verbose_name="部门")
    class Meta:
        # 表名
        db_table = 'tb_user_info'
        verbose_name = '用户'
