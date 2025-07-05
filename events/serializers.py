from rest_framework import serializers
from .models import Event, EventImage, Booking, EmergencyContact
from hosts.models import Host

class EventImageSerializer(serializers.ModelSerializer):
    image_url = serializers.SerializerMethodField()
    
    class Meta:
        model = EventImage
        fields = ['id', 'image_type', 'image', 'image_url']
    
    def get_image_url(self, obj):
        if obj.image:
            return self.context['request'].build_absolute_uri(obj.image.url)
        return None

class EmergencyContactSerializer(serializers.ModelSerializer):
    class Meta:
        model = EmergencyContact
        fields = ['id', 'name', 'phone', 'relationship', 'created_at']

class BookingSerializer(serializers.ModelSerializer):
    event_name = serializers.CharField(source='event.title', read_only=True)
    event_date = serializers.DateTimeField(source='event.date', read_only=True)
    event_location = serializers.CharField(source='event.location', read_only=True)
    event_type = serializers.CharField(source='event.type', read_only=True)
    host_name = serializers.CharField(source='host.name', read_only=True)
    emergency_contact_details = EmergencyContactSerializer(source='emergency_contact', read_only=True)
    qr_code_url = serializers.SerializerMethodField()
    status = serializers.SerializerMethodField()  # Use method field for backward compatibility
    
    class Meta:
        model = Booking
        fields = [
            'id', 'sno', 'event', 'host', 'host_name',
            'event_title', 'event_date', 'event_location',
            'event_name', 'event_type', 'user_name', 'email', 'phone', 
            'member_count', 'selected_package', 'food_preference', 
            'additional_members', 'emergency_contact', 'emergency_contact_details',
            'special_requirements', 'qr_code_url', 'status', 'is_activated', 
            'payment_method', 'payment_reference', 'payment_status', 
            'payment_amount', 'payment_currency', 'terms_accepted', 
            'privacy_policy_accepted', 'ip_address', 
            'user_agent', 'source', 'total_amount', 'created_at', 'updated_at'
        ]
        read_only_fields = ['sno', 'qr_code_url', 'created_at', 'updated_at']
    
    def get_qr_code_url(self, obj):
        if obj.qr_code:
            return self.context['request'].build_absolute_uri(obj.qr_code.url)
        return None
    
    def get_status(self, obj):
        """Get status string for backward compatibility"""
        return "Activated" if obj.is_activated else "Not Scanned"

class EventSerializer(serializers.ModelSerializer):
    event_images = EventImageSerializer(many=True, read_only=True)
    image_urls = serializers.SerializerMethodField()
    
    # Transform backend fields to frontend expectations
    id = serializers.SerializerMethodField()
    slug = serializers.CharField(read_only=True)
    title = serializers.CharField()
    description = serializers.CharField()
    tags = serializers.JSONField()
    category = serializers.CharField()
    faq = serializers.JSONField()
    termsAndConditions = serializers.CharField(source='terms_and_conditions', required=False, allow_blank=True)
    amenities = serializers.JSONField()
    images = serializers.SerializerMethodField()
    isPublished = serializers.BooleanField(source='is_published', required=False)
    packages = serializers.JSONField()
    assignedHostIds = serializers.SerializerMethodField()
    assigned_host = serializers.PrimaryKeyRelatedField(queryset=Host.objects.all(), required=True)
    additionalMembersConfig = serializers.JSONField(source='additional_members_config', required=False)
    foodPreferenceConfig = serializers.JSONField(source='food_preference_config', required=False)
    date = serializers.DateTimeField()
    end_date = serializers.DateTimeField(required=False, allow_null=True)
    start_time = serializers.TimeField(required=False, allow_null=True)
    end_time = serializers.TimeField(required=False, allow_null=True)
    location = serializers.CharField()
    status = serializers.CharField()
    type = serializers.CharField()
    
    class Meta:
        model = Event
        fields = [
            'id', 'slug', 'title', 'description', 'tags', 'category', 'faq',
            'termsAndConditions', 'amenities', 'images', 'isPublished', 'packages',
            'assignedHostIds', 'assigned_host', 'additionalMembersConfig', 'foodPreferenceConfig',
            'date', 'end_date', 'start_time', 'end_time', 'location', 'status', 'type', 'event_images', 'image_urls'
        ]
    
    def get_id(self, obj):
        return str(obj.id)
    
    def get_assignedHostIds(self, obj):
        return [str(obj.assigned_host.id)]
    
    def get_images(self, obj):
        request = self.context.get('request')
        if request and hasattr(obj, 'image_urls'):
            urls = {}
            for image_type, image_url in obj.image_urls.items():
                if image_url:
                    urls[image_type] = request.build_absolute_uri(image_url)
            return urls
        # Fallback to placeholder images if no uploaded images
        return {
            'cover': 'https://placehold.co/1200x400.png',
            'thumbnail': 'https://placehold.co/400x300.png',
            'square': 'https://placehold.co/400x400.png',
        }
    
    def get_image_urls(self, obj):
        request = self.context.get('request')
        if request and hasattr(obj, 'image_urls'):
            urls = {}
            for image_type, image_url in obj.image_urls.items():
                if image_url:
                    urls[image_type] = request.build_absolute_uri(image_url)
            return urls
        return obj.images if hasattr(obj, 'images') else {} 