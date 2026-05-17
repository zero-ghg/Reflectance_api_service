from django.db import models


class WeatherWarning(models.Model):
    """
    天气预警信息表。

    说明：
    - warning_id 对应接口字段 ID，用于唯一去重；
    - pid 对应接口字段 PID，用于解除原始预警；
    - signal_type=2 表示解除；
    - is_active 用于快速查询正在预警的数据。
    """

    warning_id = models.CharField(
        max_length=64,
        unique=True,
        db_index=True,
        verbose_name="预警信号唯一标识",
        help_text="对应接口字段 ID，用于去重",
    )
    publish_id = models.CharField(
        max_length=128,
        null=True,
        blank=True,
        verbose_name="对外发布唯一标识",
    )
    pid = models.CharField(
        max_length=64,
        null=True,
        blank=True,
        db_index=True,
        verbose_name="初起预警信号唯一标识",
        help_text="解除预警时，用 PID 找到原始预警",
    )
    warn_code = models.CharField(
        max_length=64,
        null=True,
        blank=True,
        verbose_name="预警编号",
    )

    iymdhm = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name="入库时间",
    )
    rymdhm = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name="收到时间",
    )

    warn_time = models.DateTimeField(
        null=True,
        blank=True,
        db_index=True,
        verbose_name="预警时间",
    )
    warn_period = models.CharField(
        max_length=32,
        null=True,
        blank=True,
        verbose_name="预警时效",
    )

    warn_type = models.CharField(
        max_length=32,
        null=True,
        blank=True,
        verbose_name="预警类型",
    )
    warn_level = models.CharField(
        max_length=32,
        null=True,
        blank=True,
        verbose_name="预警等级",
    )

    signal_type = models.CharField(
        max_length=8,
        null=True,
        blank=True,
        db_index=True,
        verbose_name="信号类别",
        help_text="0:初起；1:变更；2:解除",
    )
    is_active = models.BooleanField(
        default=True,
        db_index=True,
        verbose_name="是否正在预警",
        help_text="True:正在预警；False:已解除",
    )

    warn_content = models.TextField(
        null=True,
        blank=True,
        verbose_name="预警信号内容",
    )
    warn_area = models.TextField(
        null=True,
        blank=True,
        verbose_name="预警覆盖行政区编码",
        help_text="行政区编码，英文逗号分隔",
    )
    warn_measure = models.TextField(
        null=True,
        blank=True,
        verbose_name="防御指南",
    )

    area_code = models.CharField(
        max_length=64,
        null=True,
        blank=True,
        db_index=True,
        verbose_name="行政编码",
    )
    publish_unit = models.CharField(
        max_length=128,
        null=True,
        blank=True,
        verbose_name="发布单位",
    )
    status = models.CharField(
        max_length=8,
        null=True,
        blank=True,
        db_index=True,
        verbose_name="状态",
        help_text="0:待审核；1:审核中；2:审核通过；3:已发布；9:审核不通过",
    )

    make_time = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name="预警制作时间",
    )

    raw_json = models.JSONField(
        null=True,
        blank=True,
        verbose_name="接口原始JSON",
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name="创建时间",
    )
    updated_at = models.DateTimeField(
        auto_now=True,
        verbose_name="更新时间",
    )

    class Meta:
        db_table = "weather_warning"
        verbose_name = "天气预警信息"
        verbose_name_plural = "天气预警信息"
        ordering = ["-warn_time", "-id"]
        indexes = [
            models.Index(fields=["pid"], name="idx_weather_warning_pid"),
            models.Index(fields=["is_active"], name="idx_weather_warning_active"),
            models.Index(fields=["signal_type"], name="idx_weather_warning_signal"),
            models.Index(fields=["warn_time"], name="idx_weather_warning_time"),
            models.Index(fields=["area_code"], name="idx_weather_warning_area"),
            models.Index(fields=["status"], name="idx_weather_warning_status"),
            models.Index(fields=["warn_type", "warn_level"], name="idx_weather_warning_type_level"),
        ]

    def __str__(self):
        return f"{self.publish_unit or ''} {self.warn_content or self.warning_id}"