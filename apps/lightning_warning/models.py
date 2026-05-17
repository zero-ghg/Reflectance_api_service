from django.utils import timezone

from django.db import models

# Create your models here.


class TAtmoConfigTj(models.Model):
    id = models.AutoField(primary_key=True)
    device_code = models.CharField(max_length=20, verbose_name='设备编码')
    device_name = models.CharField(max_length=20, verbose_name='设备名称')
    lng = models.FloatField(verbose_name='经度', null=True, blank=True)
    lat = models.FloatField(verbose_name='纬度', null=True, blank=True)
    height = models.IntegerField(default=0, verbose_name='高度')
    province = models.CharField(max_length=50, verbose_name='省份', null=True, blank=True)
    city = models.CharField(max_length=50, verbose_name='城市', null=True, blank=True)
    county = models.CharField(max_length=50, verbose_name='县区', null=True, blank=True)
    ip = models.GenericIPAddressField(verbose_name='IP地址', null=True, blank=True)
    device_type = models.CharField(max_length=50, verbose_name='设备类型')
    append_data = models.TextField(verbose_name='附加数据', null=True, blank=True)
    update_time = models.DateTimeField(verbose_name='更新时间', null=True, blank=True)

    class Meta:
        db_table = 't_atmo_config_tj'
        verbose_name = '设备配置'
        verbose_name_plural = verbose_name

# 监测数据表
class TAtmoData(models.Model):
    time = models.DateTimeField(default=timezone.now, verbose_name="时间")
    device_id = models.IntegerField(verbose_name='设备ID',primary_key=True,)
    mesaure_value= models.FloatField(verbose_name='测量值', null=True, blank=True)
    avg_value = models.FloatField(default=0, verbose_name='平均值')
    rate = models.FloatField(default=0, verbose_name='比率')
    warn = models.IntegerField(default=0, verbose_name='预警')

    class Meta:
        db_table = 't_atmo_data'
        verbose_name = '监测数据'
        verbose_name_plural = verbose_name



