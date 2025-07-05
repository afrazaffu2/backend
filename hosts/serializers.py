from rest_framework import serializers

from .models import Host


class HostSerializer(serializers.ModelSerializer):
    id = serializers.SerializerMethodField()
    
    def get_id(self, obj):
        return str(obj.id)
    
    class Meta:
        model = Host
        fields = '__all__' 