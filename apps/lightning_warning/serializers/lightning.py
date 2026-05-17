from rest_framework import serializers
from lightning_warning.models import TAtmoConfigTj, TAtmoData

class TAtmoConfigTjSerializer(serializers.ModelSerializer):
    class Meta:
        model = TAtmoConfigTj
        fields = "__all__"

class TAtmoDataSerializer(serializers.ModelSerializer):
    class Meta:
        model = TAtmoData
        fields = "__all__"